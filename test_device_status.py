"""Offline SDK/IPv4 contracts. Never initialize the installed SDK."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).parent / 'src'))
from core.device_status import poll_devices, subnet_status, explicit_busy
from core.utils import rvc_sdk_lock


class FakeDevice:
    def __init__(self, sn='SN', port='USB', ip='192.168.1.10', mask='255.255.255.0'):
        self.info = NS(name='RVC', sn=sn, port=port)
        self.ip, self.mask = ip, mask
        self.GetNetworkConfig = Mock(return_value=(0, ip.encode(), mask.encode(), b'0.0.0.0', 0))
        self.IsFirmwareMatch = Mock(return_value=True)
        self.AutoConfigureNetwork = Mock(side_effect=AssertionError('network write forbidden'))
    def GetDeviceInfo(self):
        return True, self.info


def fixture(devices, outcomes=(True, True), error='Open failed'):
    events = []
    cameras = []
    def create(kind):
        def factory(*args):
            assert rvc_sdk_lock._is_owned()
            events.append(kind + '.Create')
            camera = Mock()
            camera.IsValid.return_value = True
            def opened():
                assert rvc_sdk_lock._is_owned()
                events.append(kind + '.Open')
                return outcomes[0 if kind == 'X2' else 1]
            camera.Open.side_effect = opened
            camera.IsOpen.return_value = outcomes[0 if kind == 'X2' else 1]
            camera.Close.side_effect = lambda: events.append(kind + '.Close')
            cameras.append(camera)
            return camera
        return factory
    sdk = NS(PortType=NS(PortType_GIGE='GigE'), NetworkDevice=NS(NetworkDevice_LightMachine=0),
             CameraID_Left=0, GetLastErrorMessage=Mock(return_value=error))
    for kind in ('X2', 'X1'):
        setattr(sdk, kind, NS(Create=Mock(side_effect=create(kind)),
                             Destroy=Mock(side_effect=lambda c, k=kind: events.append(k+'.Destroy'))))
    manager = NS(find_devices=Mock(return_value=devices), find_by_sn=Mock(return_value=None),
                 is_device_index_connected=Mock(return_value=False))
    return sdk, manager, events, cameras


class NetworkTests(unittest.TestCase):
    def test_same_and_multiple_adapters(self):
        self.assertEqual(subnet_status('192.168.1.10','255.255.255.0',
                         [('10.1.0.2','255.255.0.0'),('192.168.1.2','255.255.255.0')])[0], 'same')
    def test_mismatch_and_asymmetric_masks(self):
        for ip, mask, host in [('192.168.2.10','24','192.168.1.2'),('192.168.2.10','16','192.168.1.2')]:
            self.assertEqual(subnet_status(ip,mask,[(host,'24')])[0], 'subnet_mismatch')
    def test_invalid_missing_and_boundaries(self):
        for ip, mask in [('bad','24'),('192.168.1.1','bad'),('192.168.1.1','0'),
                         ('192.168.1.0','24'),('192.168.1.255','24'),('0.0.0.0','24')]:
            self.assertEqual(subnet_status(ip,mask,[('192.168.1.2','24')])[0], 'unknown')
        self.assertEqual(subnet_status('192.168.1.10','24',[])[0], 'unknown')
        self.assertEqual(subnet_status('192.168.1.10','32',[('192.168.1.2','24')])[0], 'subnet_mismatch')
        self.assertEqual(subnet_status('192.168.1.10','24',[('bad','24')])[0], 'unknown')
    def test_busy_is_explicit_only(self):
        for value in ('Open failed','timeout','possibly busy','network error', ''):
            self.assertFalse(explicit_busy(value))
        self.assertTrue(explicit_busy('Device is occupied'))


class PollTests(unittest.TestCase):
    def run_poll(self, devices, outcomes=(True,True), error='Open failed', hosts=None):
        self.sdk, self.manager, self.events, self.cameras = fixture(devices,outcomes,error)
        return poll_devices(self.manager,self.sdk, hosts or [('192.168.1.2','24')])
    def test_usb_idle_release_no_writes(self):
        device=FakeDevice()
        row=self.run_poll([device])[0]
        self.assertEqual(row.status,'idle')
        self.assertEqual(self.events,['X2.Create','X2.Open','X2.Close','X2.Destroy'])
        device.GetNetworkConfig.assert_not_called(); device.AutoConfigureNetwork.assert_not_called()
        for camera in self.cameras:
            camera.Capture.assert_not_called(); camera.SetBandwidth.assert_not_called()
    def test_x1_fallback(self):
        self.assertEqual(self.run_poll([FakeDevice()],(False,True))[0].status,'idle')
        self.assertEqual(self.events,['X2.Create','X2.Open','X2.Close','X2.Destroy',
                                      'X1.Create','X1.Open','X1.Close','X1.Destroy'])
    def test_busy_vs_other_failures(self):
        for message, expected in [('Device is busy','busy'),('timeout','unknown'),('Open failed','unknown')]:
            row=self.run_poll([FakeDevice()],(False,False),message)[0]
            self.assertEqual(row.status,expected); self.assertIn(message,row.detail)
            self.assertEqual(sum(e.endswith('Destroy') for e in self.events),2)
    def test_connected_sn_not_stale_index(self):
        sdk,mgr,events,_=fixture([FakeDevice()]); mgr.find_by_sn.return_value=object()
        self.assertEqual(poll_devices(mgr,sdk,[])[0].status,'connected'); self.assertEqual(events,[])
        mgr.is_device_index_connected.assert_not_called()
        mgr.find_by_sn.return_value=None; mgr.is_device_index_connected.return_value=True
        self.assertEqual(poll_devices(mgr,sdk,[])[0].status,'idle')
    def test_single_failure_preserves_rows_indices(self):
        bad=FakeDevice('bad'); bad.GetDeviceInfo=Mock(side_effect=RuntimeError('timeout'))
        rows=self.run_poll([bad,FakeDevice('good')])
        self.assertEqual([r.status for r in rows],['unknown','idle'])
        self.assertEqual([r.backend_ref for r in rows],[0,1])
        self.assertIn('timeout',rows[0].detail)
    def test_gige_network_checked_before_open_and_refresh(self):
        dev=FakeDevice(port='GigE',ip='192.168.2.10')
        self.assertEqual(self.run_poll([dev])[0].status,'subnet_mismatch'); self.assertEqual(self.events,[])
        dev.GetNetworkConfig.return_value=(0,b'192.168.1.10',b'255.255.255.0',b'0.0.0.0',0)
        self.assertEqual(poll_devices(self.manager,self.sdk,[('192.168.1.2','24')])[0].status,'idle')
        dev.AutoConfigureNetwork.assert_not_called()
    def test_network_config_error_unknown_with_ip(self):
        dev=FakeDevice(port='GigE'); dev.GetNetworkConfig.return_value=(0,b'192.168.1.10',b'',b'',3)
        row=self.run_poll([dev])[0]; self.assertEqual(row.status,'unknown'); self.assertEqual(row.ip,'192.168.1.10')
        self.assertEqual(self.events,[])
    def test_no_host_config_no_open(self):
        sdk,mgr,events,_=fixture([FakeDevice(port='GigE')])
        self.assertEqual(poll_devices(mgr,sdk,[])[0].status,'unknown'); self.assertEqual(events,[])
    def test_firmware_identity_exception_and_cleanup(self):
        dev=FakeDevice();dev.IsFirmwareMatch.return_value=False
        self.assertEqual(self.run_poll([dev])[0].status,'unknown');self.assertEqual(self.events,[])
        dev=FakeDevice();sdk,mgr,events,_=fixture([dev])
        dev.GetDeviceInfo=Mock(side_effect=[(True,dev.info),(True,NS(sn='other',name='RVC'))])
        row=poll_devices(mgr,sdk,[])[0];self.assertEqual(row.status,'unknown');self.assertIn('身份',row.detail)
        self.assertEqual(events[-2:],['X2.Close','X2.Destroy']); sdk.X1.Create.assert_not_called()
        sdk,mgr,events,cameras=fixture([FakeDevice()]);sdk.X2.Create.side_effect=RuntimeError('create failure')
        self.assertEqual(poll_devices(mgr,sdk,[])[0].status,'idle')
    def test_open_exception_is_cleaned(self):
        sdk,mgr,events,cameras=fixture([FakeDevice()])
        original=sdk.X2.Create.side_effect
        def make(*args):
            camera=original(*args);camera.Open.side_effect=RuntimeError('timeout');return camera
        sdk.X2.Create.side_effect=make
        self.assertEqual(poll_devices(mgr,sdk,[])[0].status,'idle')
        self.assertIn('X2.Close',events);self.assertIn('X2.Destroy',events)

if __name__=='__main__': unittest.main()
