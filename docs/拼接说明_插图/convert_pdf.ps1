$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
$src = 'D:\RVC_SRC\Python\MultiCameraCalibration\docs\3D相机拼接方案通俗说明.docx'
$dst = 'D:\RVC_SRC\Python\MultiCameraCalibration\docs\3D相机拼接方案通俗说明.pdf'
$doc = $word.Documents.Open($src)
$doc.SaveAs([ref]$dst, [ref]17)
$doc.Close($false)
$word.Quit()
Write-Output 'PDF_OK'
