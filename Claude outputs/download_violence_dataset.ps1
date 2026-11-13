$ErrorActionPreference = "Stop"
$root = Join-Path $env:USERPROFILE "Downloads\Violence_AI_10000"
$downloads = Join-Path $root "_downloads"
$temp = Join-Path $root "_extracting"
$videoRoot = Join-Path $root "videos"
$imageRoot = Join-Path $root "images"
$toolsRoot = Join-Path $root "_tools"

# Muc tieu tong (video + anh) cho MOI lop (bao luc / binh thuong). Giu can bang
# 2 lop la BAT BUOC de huan luyen mot bo phan loai nhi phan dung nghia - neu chi
# co lop bao luc, model se khong biet "binh thuong" trong nhu the nao va se bao
# dong gia lien tuc voi bat ky chuyen dong nao.
$targetPerClass = 5000
$labels = @("violence", "non_violence")

$datasets = @(
 @{Name="bus_cctv"; Url="https://zenodo.org/records/7044203/files/bus-violence.zip?download=1"; Zip="bus.zip"; Md5="e2cf7e55ac63b20bda485186249f4b60"},
 @{Name="street_real_life"; Url="https://www.kaggle.com/api/v1/datasets/download/mohamedmustafa/real-life-violence-situations-dataset"; Zip="street.zip"; Md5=""},
 @{Name="hockey_fights"; Url="https://www.kaggle.com/api/v1/datasets/download/yassershrief/hockey-fight-vidoes"; Zip="hockey.zip"; Md5=""}
)

function Download-File($url, $out) {
 if (Test-Path $out) { return }
 $ProgressPreference = "SilentlyContinue"
 try { Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -MaximumRedirection 10 }
 catch {
  if (Test-Path $out) { Remove-Item -Force $out }
  throw "Khong tai duoc nguon. Neu la Kaggle, hay dang nhap Kaggle tren trinh duyet va chay lai. $($_.Exception.Message)"
 }
}

# Tra ve "violence", "non_violence", hoac $null (khong xac dinh duoc - bo qua file).
# QUAN TRONG: khac ban truoc (chi giu "violence"), ham nay giu CA HAI lop vi ca 3
# nguon du lieu deu co san lop "binh thuong" di kem, chi la ban truoc loai bo no.
function Classify-File($file, $source) {
 $p = $file.FullName.ToLowerInvariant()
 if ($source -eq "bus_cctv") {
  if ($p -match "[\\/]violence[\\/]" -and $p -notmatch "non.?violence") { return "violence" }
  if ($p -match "[\\/]non.?violence[\\/]") { return "non_violence" }
  return $null
 }
 if ($source -eq "street_real_life") {
  if (($p -match "[\\/]violence[\\/]" -and $p -notmatch "non.?violence") -or $file.BaseName -match "^V_") { return "violence" }
  if (($p -match "[\\/]non.?violence[\\/]") -or $file.BaseName -match "^NV_") { return "non_violence" }
  return $null
 }
 if ($source -eq "hockey_fights") {
  if ($p -match "[\\/](fi|fight)(s)?[\\/]" -or $file.BaseName -match "^(fi|fight)") { return "violence" }
  if ($p -match "[\\/]no[\\/]" -or $file.BaseName -match "^no") { return "non_violence" }
  return $null
 }
 return $null
}

New-Item -ItemType Directory -Force -Path $root,$downloads,$temp,$toolsRoot | Out-Null
foreach ($lbl in $labels) {
 New-Item -ItemType Directory -Force -Path (Join-Path $videoRoot $lbl),(Join-Path $imageRoot $lbl) | Out-Null
}
$exts = @(".avi",".mp4",".mov",".mkv",".webm",".mpeg",".mpg")

# $byLabel.violence / $byLabel.non_violence = danh sach FileInfo da duoc phan loai
$byLabel = @{ violence = New-Object System.Collections.Generic.List[System.IO.FileInfo];
              non_violence = New-Object System.Collections.Generic.List[System.IO.FileInfo] }

foreach ($ds in $datasets) {
 $archive = Join-Path $downloads $ds.Zip
 $unpack = Join-Path $temp $ds.Name
 Write-Host "Dang tai $($ds.Name)..." -ForegroundColor Cyan
 Download-File $ds.Url $archive
 if ($ds.Md5) {
  $actual = (Get-FileHash -Algorithm MD5 $archive).Hash.ToLowerInvariant()
  if ($actual -ne $ds.Md5) { Remove-Item -Force $archive; throw "Checksum sai. Hay chay lai." }
 }
 if (Test-Path $unpack) { Remove-Item -Recurse -Force $unpack }
 New-Item -ItemType Directory -Force -Path $unpack | Out-Null
 Expand-Archive -LiteralPath $archive -DestinationPath $unpack -Force

 $dsCounts = @{ violence = 0; non_violence = 0 }
 foreach ($f in (Get-ChildItem $unpack -File -Recurse | Where-Object { $exts -contains $_.Extension.ToLowerInvariant() })) {
  $label = Classify-File $f $ds.Name
  if (-not $label) { continue }
  $i = $byLabel[$label].Count + 1
  $output = Join-Path $videoRoot $label $ds.Name
  New-Item -ItemType Directory -Force -Path $output | Out-Null
  $name = "{0}_{1:D4}{2}" -f $ds.Name,$i,$f.Extension.ToLowerInvariant()
  $dest = Join-Path $output $name
  Copy-Item -LiteralPath $f.FullName -Destination $dest -Force
  $byLabel[$label].Add((Get-Item $dest))
  $dsCounts[$label]++
 }
 if (($dsCounts.violence + $dsCounts.non_violence) -eq 0) { throw "Khong phan loai duoc file nao trong $($ds.Name)." }
 Write-Host ("Da giu {0}: violence={1}, non_violence={2}" -f $ds.Name,$dsCounts.violence,$dsCounts.non_violence) -ForegroundColor Green
}

foreach ($lbl in $labels) {
 if ($byLabel[$lbl].Count -lt 300) {
  Write-Warning "Lop '$lbl' chi co $($byLabel[$lbl].Count) video - hoi it, kiem tra lai Classify-File neu can."
 }
}

$ffmpeg = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
$ffprobe = Get-Command ffprobe.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1
if (-not $ffmpeg -or -not $ffprobe) {
 $ffZip = Join-Path $downloads "ffmpeg.zip"
 $ffSha = Join-Path $downloads "ffmpeg.zip.sha256"
 Download-File "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" $ffZip
 Download-File "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip.sha256" $ffSha
 $expected = ((Get-Content $ffSha -Raw).Trim() -split "\s+")[0].ToLowerInvariant()
 $actual = (Get-FileHash -Algorithm SHA256 $ffZip).Hash.ToLowerInvariant()
 if ($expected -ne $actual) { throw "Checksum FFmpeg sai." }
 $ffDir = Join-Path $toolsRoot "ffmpeg"
 Expand-Archive -LiteralPath $ffZip -DestinationPath $ffDir -Force
 $ffmpeg = (Get-ChildItem $ffDir -Filter ffmpeg.exe -File -Recurse | Select-Object -First 1).FullName
 $ffprobe = (Get-ChildItem $ffDir -Filter ffprobe.exe -File -Recurse | Select-Object -First 1).FullName
}

# Voi MOI lop rieng: neu con thieu de dat $targetPerClass, cat them anh tu video
# cua DUNG lop do de bu vao - khong bao gio tron lan anh cua lop nay sang lop kia.
$madeTotal = @{ violence = 0; non_violence = 0 }
foreach ($lbl in $labels) {
 $videos = $byLabel[$lbl]
 if ($videos.Count -eq 0) { continue }
 $targetImages = [Math]::Max(0, $targetPerClass - $videos.Count)
 if ($targetImages -eq 0) { continue }
 $base = [Math]::Floor($targetImages / $videos.Count)
 $extra = $targetImages % $videos.Count
 $n = 0
 foreach ($v in $videos) {
  $n++; $wanted = $base; if ($n -le $extra) { $wanted++ }; if ($wanted -le 0) { continue }
  $durationText = (& $ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 -- "$($v.FullName)" | Select-Object -First 1).Trim()
  $duration = 0.0
  [void][double]::TryParse($durationText,[System.Globalization.NumberStyles]::Float,[System.Globalization.CultureInfo]::InvariantCulture,[ref]$duration)
  if ($duration -le 0) { continue }
  $fps = ($wanted/$duration).ToString("0.############",[System.Globalization.CultureInfo]::InvariantCulture)
  $source = Split-Path $v.DirectoryName -Leaf
  $frameDir = Join-Path $imageRoot $lbl $source
  New-Item -ItemType Directory -Force -Path $frameDir | Out-Null
  $pattern = Join-Path $frameDir ($v.BaseName+"_frame_%02d.jpg")
  & $ffmpeg -hide_banner -loglevel error -i "$($v.FullName)" -vf "fps=$fps" -frames:v $wanted -q:v 2 -y "$pattern"
  $madeTotal[$lbl] += @(Get-ChildItem $frameDir -Filter ($v.BaseName+"_frame_*.jpg") -File).Count
  if (($n % 100) -eq 0) { Write-Host "[$lbl] Da xu ly $n/$($videos.Count) video - $($madeTotal[$lbl]) anh" }
 }
}

$totalViolence = $byLabel.violence.Count + $madeTotal.violence
$totalNonViolence = $byLabel.non_violence.Count + $madeTotal.non_violence
$manifest=@"
VIOLENCE AI DATASET - MIXED SOURCES (2 LOP: violence / non_violence)
Violence: $($byLabel.violence.Count) video + $($madeTotal.violence) anh = $totalViolence
Non-violence: $($byLabel.non_violence.Count) video + $($madeTotal.non_violence) anh = $totalNonViolence
Tong: $($totalViolence + $totalNonViolence)
Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

Cau truc thu muc:
videos/violence/<nguon>/...        videos/non_violence/<nguon>/...
images/violence/<nguon>/...        images/non_violence/<nguon>/...

Sources:
Bus Violence: https://zenodo.org/records/7044203
Real Life Violence: https://www.kaggle.com/datasets/mohamedmustafa/real-life-violence-situations-dataset
Hockey Fight: https://www.kaggle.com/datasets/yassershrief/hockey-fight-vidoes

Review each source license before commercial use.
"@
Set-Content (Join-Path $root "DATASET_MANIFEST.txt") $manifest -Encoding UTF8
Remove-Item -Recurse -Force $temp,$downloads,$toolsRoot
Write-Host ("HOAN TAT - violence: {0} | non_violence: {1} | tong: {2}" -f $totalViolence,$totalNonViolence,($totalViolence+$totalNonViolence)) -ForegroundColor Green
if ([Math]::Abs($totalViolence - $totalNonViolence) -gt ($targetPerClass * 0.3)) {
 Write-Warning "2 lop dang lech kha nhieu (violence=$totalViolence, non_violence=$totalNonViolence) - can nhac them nguon hoac bot bot lop nhieu hon truoc khi huan luyen."
}
