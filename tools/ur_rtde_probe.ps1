# UR RTDE (port 30004) probe -- run this on the PC that talks to the robot.
#
# Why this exists: the 30003 realtime port hands out a fixed binary blob, and
# reading the TCP pose from it means trusting a hard-coded byte offset (that is
# exactly how the tool reported a TCP pose of (0,0,0,0,0,0) on 2026-10-10 --
# the offset was one 48-byte field too far and landed on actual_TCP_speed).
# RTDE is the interface UR recommends instead: the client asks for
# "actual_TCP_pose" BY NAME, so there is no offset to get wrong. It is not a
# drop-in port change though -- it is a short handshake first:
#
#   1. RTDE_REQUEST_PROTOCOL_VERSION (86)       -> answered accepted(1/0)
#   2. RTDE_CONTROL_PACKAGE_SETUP_OUTPUTS (79)  -> frequency + variable names,
#                                                  answered recipe id + types
#   3. RTDE_CONTROL_PACKAGE_START (83)          -> controller starts streaming
#   4. RTDE_DATA_PACKAGE (85)                   -> recipe id + the values
#
# This script runs that handshake and prints the pose, so the whole question
# ("does this robot do RTDE, and does the pose match the pendant?") is answered
# in two minutes, with no build to install.
#
# Usage (robot powered on):
#   powershell -ExecutionPolicy Bypass -File ur_rtde_probe.ps1 -RobotIp 192.168.1.10
#
# Put the robot at the same pose you compared on the pendant and pass its
# numbers so the script can check them:
#   ... -RobotIp 192.168.1.10 -Expected "0,193.74,1000.96,0,2.224,2.219"
#   (xyz in mm, rx/ry/rz raw -- the pendant shows the rotation vector in radians)
#
# What to send back: the whole printed output.
#
# NOTE: 'NOT_FOUND' at step 2 means the controller did not recognise the name
# it was asked for. Two causes: something else on the network already holds the
# single RTDE output recipe (another tool, a URCap, a running program), or the
# name list itself is malformed -- an extra terminator turns
# "actual_TCP_pose" into a name that does not exist. The payload below is the
# one UR's own client sends; if it still answers NOT_FOUND, disconnect the
# other client.

param(
    [Parameter(Mandatory = $true)][string]$RobotIp,
    [int]$Port = 30004,
    [string]$Expected = "",
    [int]$TimeoutMs = 5000
)

$ErrorActionPreference = "Stop"

function Read-Exact {
    param([System.IO.Stream]$Stream, [int]$Count)
    $buf = New-Object byte[] $Count
    $got = 0
    while ($got -lt $Count) {
        $r = $Stream.Read($buf, $got, $Count - $got)
        if ($r -le 0) { throw "stream closed after $got of $Count bytes" }
        $got += $r
    }
    , $buf
}

# Big-endian double at $Offset (RTDE is network byte order throughout).
function Get-BEDouble {
    param([byte[]]$Bytes, [int]$Offset)
    $tmp = New-Object byte[] 8
    for ($i = 0; $i -lt 8; $i++) { $tmp[$i] = $Bytes[$Offset + 7 - $i] }
    [BitConverter]::ToDouble($tmp, 0)
}

# Every RTDE packet: [uint16 BE size (includes this header)][uint8 type][payload]
function Send-Cmd {
    param([System.IO.Stream]$Stream, [byte]$Type, [byte[]]$Payload)
    if ($null -eq $Payload) { $Payload = New-Object byte[] 0 }
    $size = $Payload.Length + 3
    $pkt = New-Object byte[] $size
    $pkt[0] = [byte](($size -shr 8) -band 0xFF)
    $pkt[1] = [byte]($size -band 0xFF)
    $pkt[2] = $Type
    if ($Payload.Length -gt 0) { [Array]::Copy($Payload, 0, $pkt, 3, $Payload.Length) }
    $Stream.Write($pkt, 0, $size)
    $Stream.Flush()
}

function Read-Packet {
    param([System.IO.Stream]$Stream)
    $head = Read-Exact -Stream $Stream -Count 3
    $size = ([int]$head[0] -shl 8) -bor [int]$head[1]
    if ($size -lt 3) { throw "implausible RTDE packet size: $size" }
    $body = if ($size -gt 3) { Read-Exact -Stream $Stream -Count ($size - 3) } else { New-Object byte[] 0 }
    [pscustomobject]@{ Type = $head[2]; Body = $body; Head = $head }
}

function Get-HexDump {
    param([byte[]]$Bytes, [int]$Count)
    $sb = New-Object System.Text.StringBuilder
    $n = [Math]::Min($Count, $Bytes.Length)
    for ($i = 0; $i -lt $n; $i++) {
        if ($i % 16 -eq 0) { [void]$sb.Append(("{0,5}: " -f $i)) }
        [void]$sb.Append(("{0:X2} " -f $Bytes[$i]))
        if ($i % 16 -eq 15) { [void]$sb.AppendLine() }
    }
    $sb.ToString()
}

# ------------------------------------------------------------------ connect

Write-Host ("connecting to {0}:{1} ..." -f $RobotIp, $Port)
$client = New-Object System.Net.Sockets.TcpClient
$client.ReceiveTimeout = $TimeoutMs
$client.Connect($RobotIp, $Port)
$stream = $client.GetStream()
Write-Host "connected"

# ------------------------------------------------- 1. protocol version (v2)

Send-Cmd -Stream $stream -Type 86 -Payload ([byte[]]@(0, 2))
$r = Read-Packet -Stream $stream
$accepted = if ($r.Body.Length -ge 1) { [int]$r.Body[0] } else { -1 }
Write-Host ("REQUEST_PROTOCOL_VERSION(2) -> accepted={0}" -f $accepted)
if ($accepted -ne 1) {
    throw ("controller refused RTDE protocol version 2. Older controllers only " +
           "speak version 1, which lays out the output setup differently; " +
           "check the software version on the pendant (About) -- RTDE needs " +
           "CB3 software 3.3+, and version 2 came later.")
}

# ------------------------------------------------- 2. output recipe by name

$freq = [BitConverter]::GetBytes([double]125.0)
[Array]::Reverse($freq)                                  # -> big endian
# Names are COMMA separated and the list has NO trailing separator: the packet
# length delimits the last name. That is what UR's own client library sends
# (control_package_setup_outputs.cpp: names joined with "," then pop_back()).
# A trailing NUL is read as part of the name and the controller answers
# NOT_FOUND -- measured on a live controller 2026-10-10, and the reason the
# first version of this handshake failed to connect.
$name = [System.Text.Encoding]::ASCII.GetBytes("actual_TCP_pose")
$pay = New-Object byte[] (8 + $name.Length)
[Array]::Copy($freq, 0, $pay, 0, 8)
[Array]::Copy($name, 0, $pay, 8, $name.Length)
Send-Cmd -Stream $stream -Type 79 -Payload $pay
$r = Read-Packet -Stream $stream
$recipeId = if ($r.Body.Length -ge 1) { [int]$r.Body[0] } else { -1 }
$types = ""
if ($r.Body.Length -gt 1) {
    $types = [System.Text.Encoding]::ASCII.GetString($r.Body, 1, $r.Body.Length - 1).Trim([char]0)
}
Write-Host ("SETUP_OUTPUTS('actual_TCP_pose') -> recipe id {0}, type '{1}'" -f $recipeId, $types)
if ($types -notlike "VECTOR6D*") {
    throw ("the controller did not offer actual_TCP_pose as VECTOR6D " +
           "(got '$types'). Either another RTDE client holds the single " +
           "output recipe, or this controller does not know that name -- " +
           "disconnect the other client and retry before concluding anything.")
}

# ------------------------------------------------------------ 3. start push

Send-Cmd -Stream $stream -Type 83 -Payload (New-Object byte[] 0)
$r = Read-Packet -Stream $stream
Write-Host ("CONTROL_START -> accepted={0}" -f $r.Body[0])

# ------------------------------------------------------- 4. first data packet

$r = $null
for ($i = 0; $i -lt 50; $i++) {
    $r = Read-Packet -Stream $stream
    if ($r.Type -eq 85) { break }
    Write-Host ("  (skipped package type {0}, {1} bytes)" -f $r.Type, $r.Body.Length)
}
if ($null -eq $r -or $r.Type -ne 85) { throw "no RTDE data package arrived" }

# Data payload = recipe id + the requested values. Decide the offset by length
# rather than assuming the recipe id byte, so a one-byte shift cannot quietly
# misread every double.
$off = if ($r.Body.Length -ge 49) { 1 } else { 0 }
$vals = New-Object double[] 6
for ($k = 0; $k -lt 6; $k++) { $vals[$k] = Get-BEDouble -Bytes $r.Body -Offset ($off + $k * 8) }

Write-Host ""
Write-Host ("data package: recipe id {0}, {1} bytes (values start at {2})" -f `
    ([int]$r.Body[0]), $r.Body.Length, $off)
Write-Host "data package head (hex):"
Write-Host (Get-HexDump -Bytes $r.Body -Count 16)
Write-Host ""
Write-Host ("actual_TCP_pose (base frame):")
Write-Host ("  x={0:F4} y={1:F4} z={2:F4} m   rx={3:F6} ry={4:F6} rz={5:F6} rad" -f `
    $vals[0], $vals[1], $vals[2], $vals[3], $vals[4], $vals[5])
Write-Host ("  = {0:F2}, {1:F2}, {2:F2} mm    {3:F4}, {4:F4}, {5:F4} rad" -f `
    ($vals[0] * 1000.0), ($vals[1] * 1000.0), ($vals[2] * 1000.0), `
    $vals[3], $vals[4], $vals[5])
Write-Host ("  rotation-vector magnitude = {0:F4} rad ({1:F2} deg)" -f `
    [Math]::Sqrt($vals[3] * $vals[3] + $vals[4] * $vals[4] + $vals[5] * $vals[5]), `
    (180.0 / [Math]::PI * [Math]::Sqrt($vals[3] * $vals[3] + $vals[4] * $vals[4] + $vals[5] * $vals[5])))

if ($Expected) {
    $want = @()
    foreach ($piece in $Expected.Split(",")) { $want += [double]$piece.Trim() }
    if ($want.Count -ne 6) { throw "-Expected needs 6 comma-separated numbers" }
    Write-Host ""
    Write-Host ("against the pendant's {0} (xyz compared in mm, rx/ry/rz raw):" -f $Expected)
    $worst = 0.0
    for ($k = 0; $k -lt 6; $k++) {
        $v = $vals[$k]
        if ($k -lt 3) { $v = $v * 1000.0 }
        $d = [Math]::Abs($v - $want[$k])
        Write-Host ("  component {0}: got {1:F4} want {2:F4} diff {3:F4}" -f $k, $v, $want[$k], $d)
        if ($d -gt $worst) { $worst = $d }
    }
    Write-Host ("  -> worst component difference {0:F4}" -f $worst)
    if ($worst -lt 0.5) {
        Write-Host "  -> MATCH. This robot's RTDE gives the same pose as the pendant."
    } else {
        Write-Host "  -> MISMATCH. Send this output back."
    }
}

$stream.Close()
$client.Close()
