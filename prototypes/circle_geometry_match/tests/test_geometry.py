import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
import unittest
import cv2
import numpy as np
from prototypes.circle_geometry_match.core.circles import CircleParameters,detect_circles
from prototypes.circle_geometry_match.core.matching import MatchParameters,match_geometry

class CircleTests(unittest.TestCase):
    def frame(self,polarity='dark'):
        image=np.full((180,240),255 if polarity=='dark' else 0,np.uint8)
        for x,y in [(35,35),(170,40),(65,130)]:cv2.circle(image,(x,y),9,0 if polarity=='dark' else 255,-1)
        yy,xx=np.mgrid[:180,:240];points=np.stack((xx,yy,np.full_like(xx,400)),axis=-1).astype(float)
        return image,points

    def test_black_white_circle_detection_and_invalid_depth(self):
        for polarity in ('dark','light'):
            image,points=self.frame(polarity)
            dots=detect_circles(image,points.reshape(-1,3),CircleParameters(polarity=polarity))
            self.assertEqual(len(dots),3)
            self.assertTrue(all(dot['valid_3d'] for dot in dots))
            for dot in dots:np.testing.assert_allclose(dot['xyz'][:2],dot['pixel'],atol=.01)
        image,points=self.frame()
        points[25:46,25:46]=0
        dots=detect_circles(image,points.reshape(-1,3))
        self.assertEqual(sum(dot['valid_3d'] for dot in dots),2)

    def test_organized_mapping_ring_and_parameter_guards(self):
        image,points=self.frame()
        with self.assertRaises(ValueError):detect_circles(image,points.reshape(-1,3)[:-1])
        with self.assertRaises(ValueError):detect_circles(image,points.reshape(-1,3),CircleParameters(min_radius=100,max_radius=3))
        cv2.circle(image,(200,130),12,0,2)
        self.assertEqual(len(detect_circles(image,points.reshape(-1,3))),3)

class TriangleTests(unittest.TestCase):
    def scene(self):
        reference=np.array([[0,0,300],[47,0,300],[13,32,300],[69,65,301],[5,81,310]],float)
        rotation=cv2.Rodrigues(np.array([.2,-.3,.1]))[0];translation=np.array([31,-22,51])
        moving=(reference-translation)@rotation
        transform=np.eye(4);transform[:3,:3]=rotation;transform[:3,3]=translation
        return reference,moving,transform

    def test_scalene_triangle_shuffled_direction_and_no_scale(self):
        a,b,t=self.scene();order=[2,0,1]
        match=match_geometry(a[:3],b[order],MatchParameters(edge_tolerance=.01,relative_tolerance=0,point_tolerance=.02))
        np.testing.assert_allclose(match['transform'],t,atol=1e-9)
        self.assertEqual(len(match['pairs']),3)
        with self.assertRaises(ValueError):match_geometry(a[:3],b[:3]*1000)

    def test_consensus_with_missing_dots_noise_and_clutter(self):
        a,b,t=self.scene();rng=np.random.default_rng(42)
        a=np.vstack((a,[[200,200,200]]));b=np.vstack((b[[3,0,2,1]]+rng.normal(0,.005,(4,3)),[[-200,0,200]]))
        result=match_geometry(a,b,MatchParameters(edge_tolerance=.1,relative_tolerance=0,point_tolerance=.1,min_matches=4))
        self.assertEqual(len(result['pairs']),4)
        self.assertLess(result['rms'],.02)
        np.testing.assert_allclose(result['transform'][:3,3],t[:3,3],atol=.2)

    def test_ambiguity_degenerate_and_budget_rejected(self):
        for a in (np.array([[0,0,0],[20,0,0],[10,np.sqrt(3)*10,0]]),
                  np.array([[0,0,0],[20,0,0],[10,30,0]]),
                  np.array([[0,0,0],[10,0,0],[30,0,0]])):
            with self.assertRaises(ValueError):match_geometry(a,a)
        a,b,_=self.scene()
        with self.assertRaisesRegex(ValueError,'候选过多'):match_geometry(a,b,MatchParameters(max_hypotheses=1))
        with self.assertRaises(ValueError):match_geometry(a,b,shape='polygon')
        with self.assertRaises(ValueError):match_geometry(a,b,MatchParameters(point_tolerance=float('nan')))

if __name__=='__main__':unittest.main()
