# UR realtime (port 30003) packet probe -- run this on the PC that talks to the robot.
#
# Why this exists: on the real robot the tool reported a TCP pose of
# (0, 0, 0, 0, 0, 0) while the pendant showed a real base-frame pose
# (0, 193.74, 1000.96, 0, 2.224, 2.219). Six exact zeros are not a failed parse --
# they are a *velocity* field (a real controller field that is zero whenever the
# arm stands still) sitting one 48-byte block away from the pose. So the
# hard-coded body offset in src/logic/URRealtimeReader.cpp is wrong, but the
# right value must come from the robot, not from a document: capture a real
# packet and read off which 48-byte block carries the pose.
#
# Usage (robot powered on, at whatever pose you like):
#   powershell -ExecutionPolicy Bypass -File ur_realtime_probe.ps1 -RobotIp 192.168.1.10
#
# Recommended: put the robot at the SAME pose you compared with the pendant, and
# pass the pendant's numbers so the script points at the matching block:
#   ... -RobotIp 192.168.1.10 -Expected "0,193.74,1000.96,0,2.224,2.219"
#
# What to send back: the whole printed output (it is one packet, a few kB of text).
#
# -FromFile <path> replays a captured packet instead of opening a socket, so the
# decoding can be checked offline.

param(
    [string]$RobotIp = "",
    [int]$Port = 30003,
    [string]$Expected = "",
    [string]$FromFile = "",
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

# Big-endian double at $Offset (the realtime stream is network byte order).
function Get-BEDouble {
    param([byte[]]$Bytes, [int]$Offset)
    $tmp = New-Object byte[] 8
    for ($i = 0; $i -lt 8; $i++) { $tmp[$i] = $Bytes[$Offset + 7 - $i] }
    [BitConverter]::ToDouble($tmp, 0)
}

function Get-BEInt32 {
    param([byte[]]$Bytes, [int]$Offset)
    ([int]$Bytes[$Offset] -shl 24) -bor ([int]$Bytes[$Offset + 1] -shl 16) `
        -bor ([int]$Bytes[$Offset + 2] -shl 8) -bor [int]$Bytes[$Offset + 3]
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

# ---------------------------------------------------------------- get one packet

$raw = $null
if ($FromFile) {
    $raw = [System.IO.File]::ReadAllBytes($FromFile)
    Write-Host ("source: file {0} ({1} bytes)" -f $FromFile, $raw.Length)
}
elseif ($RobotIp) {
    Write-Host ("connecting to {0}:{1} ..." -f $RobotIp, $Port)
    $client = New-Object System.Net.Sockets.TcpClient
    $client.ReceiveTimeout = $TimeoutMs
    $client.Connect($RobotIp, $Port)
    $stream = $client.GetStream()
    $hdr = Read-Exact -Stream $stream -Count 4
    $len = Get-BEInt32 -Bytes $hdr -Offset 0
    if ($len -lt 4 -or $len -gt 8192) { throw "implausible length prefix: $len" }
    $body = Read-Exact -Stream $stream -Count ($len - 4)
    $raw = New-Object byte[] $len
    [Array]::Copy($hdr, 0, $raw, 0, 4)
    [Array]::Copy($body, 0, $raw, 4, $len - 4)
    $stream.Close()
    $client.Close()
    Write-Host "connected, one packet read"
}
else {
    throw "give either -RobotIp or -FromFile"
}

$len = Get-BEInt32 -Bytes $raw -Offset 0
if ($len -lt 4 -or $len -gt 8192) { throw "implausible length prefix: $len" }
if ($len -gt $raw.Length) { throw "packet truncated: header says $len, have $($raw.Length)" }

# body = everything after the 4-byte length, which is what the C++ reader indexes into
$body = New-Object byte[] ($len - 4)
[Array]::Copy($raw, 4, $body, 0, $len - 4)

Write-Host ""
Write-Host ("message length : {0} (body {1})" -f $len, $body.Length)
Write-Host ("first double   : {0}   <- controller time, should be a plausible positive number" `
    -f (Get-BEDouble -Bytes $body -Offset 0))
Write-Host ""
Write-Host "head (hex):"
Write-Host (Get-HexDump -Bytes $raw -Count 64)

# ------------------------------------------------- blocks the C++ reader assumes

$cur = New-Object string[] 6
for ($k = 0; $k -lt 6; $k++) {
    $cur[$k] = "{0,14:F6}" -f (Get-BEDouble -Bytes $body -Offset (200 + $k * 8))
}
Write-Host ""
Write-Host ("body offset 200 (what URRealtimeReader.cpp reads today): {0}" -f ($cur -join " "))

# ------------------------------------------------------------------ block table
# The leading field is the 8-byte time, so every 6-double field sits at 8 + 48k.

Write-Host ""
Write-Host "every 6-double field (index = byte offset in the body, fields are 8 + 48k):"
Write-Host "  [off]              v0             v1             v2             v3             v4             v5"
for ($off = 8; $off + 48 -le $body.Length; $off += 48) {
    $vals = New-Object string[] 6
    for ($k = 0; $k -lt 6; $k++) {
        $vals[$k] = "{0,14:F6}" -f (Get-BEDouble -Bytes $body -Offset ($off + $k * 8))
    }
    Write-Host ("  [{0,4}] {1}" -f $off, ($vals -join " "))
}

# ------------------------------------------------- match the pendant's numbers

if ($Expected) {
    $want = @()
    foreach ($piece in $Expected.Split(",")) { $want += [double]$piece.Trim() }
    if ($want.Count -ne 6) { throw "-Expected needs 6 comma-separated numbers" }

    Write-Host ""
    Write-Host ("best match for the pendant's {0} (xyz compared in mm, rx/ry/rz raw):" -f $Expected)
    # Scan every 8-byte-aligned window, so a field that is NOT at 8 + 48k is still found.
    $best = $null
    for ($off = 8; $off + 48 -le $body.Length; $off += 8) {
        $worst = 0.0
        for ($k = 0; $k -lt 6; $k++) {
            $v = Get-BEDouble -Bytes $body -Offset ($off + $k * 8)
            if ($k -lt 3) { $v = $v * 1000.0 }   # packet xyz is metres, pendant is mm
            $d = [Math]::Abs($v - $want[$k])
            if ($d -gt $worst) { $worst = $d }
        }
        if ($null -eq $best -or $worst -lt $best.Worst) {
            $best = [pscustomobject]@{ Offset = $off; Worst = $worst }
        }
    }
    Write-Host ("  -> best block at body offset {0}, worst component difference {1:F4}" -f $best.Offset, $best.Worst)
    Write-Host "  -> the pose is the block where that difference is ~0. If it is not 200,"
    Write-Host "     URRealtimeReader.cpp's constant is wrong; send this output back."
}
