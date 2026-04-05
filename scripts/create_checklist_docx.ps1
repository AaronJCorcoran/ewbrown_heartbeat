<#
.SYNOPSIS
    Creates EW Brown Field Checklist as a .docx file with clickable checkboxes.
    Uses System.IO.Compression (no Word installation required).
#>

$outPath = "C:\Users\aaron\Documents\EW_Brown_setup\ew_brown_heartbeat_bundle\ew_brown_heartbeat_bundle\EW_Brown_Field_Checklist.docx"

# Helper: checkbox symbol (Unicode ballot box)
$checkbox = [char]0x2610  # empty checkbox character

# Build the document.xml content
$body = @"
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
            xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">
<w:body>

  <!-- Title -->
  <w:p><w:pPr><w:pStyle w:val="Title"/><w:jc w:val="center"/></w:pPr>
    <w:r><w:rPr><w:b/><w:sz w:val="48"/></w:rPr><w:t>EW BROWN FIELD CHECKLIST</w:t></w:r></w:p>

  <w:p/>

  <!-- ARRIVAL INSPECTION -->
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="32"/></w:rPr><w:t>ARRIVAL INSPECTION</w:t></w:r></w:p>

  <w:p><w:r><w:rPr><w:b/><w:sz w:val="24"/></w:rPr><w:t>Equipment Cabinet:</w:t></w:r></w:p>

  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>${checkbox}</w:t></w:r>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">  Power strip — orange light ON</w:t></w:r></w:p>

  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>${checkbox}</w:t></w:r>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">  RUT241 router — 3 small green lights blinking</w:t></w:r></w:p>

  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>${checkbox}</w:t></w:r>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">  Netgear switch — green power light ON, green lights on three grey ethernet ports, orange light on blue LAN port</w:t></w:r></w:p>

  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>${checkbox}</w:t></w:r>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">  Pi — green AND orange lights on ethernet port</w:t></w:r></w:p>

  <w:p/>

  <!-- HARD DRIVE SWAP -->
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="32"/></w:rPr><w:t>HARD DRIVE SWAP PROCEDURE</w:t></w:r></w:p>

  <w:p><w:pPr><w:jc w:val="center"/></w:pPr>
    <w:r><w:rPr><w:b/><w:color w:val="FF0000"/><w:sz w:val="24"/></w:rPr>
    <w:t>*** CRITICAL TO FOLLOW THIS ORDER PRECISELY ***</w:t></w:r></w:p>

  <w:p/>

  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t>1.  Unplug power to Pi</w:t></w:r></w:p>
  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t>2.  Swap SSD hard drive (leave cable in place)</w:t></w:r></w:p>
  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t>3.  Confirm new drive is fully seated</w:t></w:r></w:p>
  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t>4.  Plug power back into Pi</w:t></w:r></w:p>
  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t>5.  Wait 60 seconds for Pi to fully boot</w:t></w:r></w:p>
  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t>6.  Write today's date and your initials on the removed drive</w:t></w:r></w:p>
  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t>7.  Write today's date and initials on log in enclosure</w:t></w:r></w:p>

  <w:p/>

  <!-- DEPARTURE CONFIRMATION -->
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="32"/></w:rPr><w:t>DEPARTURE CONFIRMATION</w:t></w:r></w:p>

  <w:p><w:pPr><w:jc w:val="center"/></w:pPr>
    <w:r><w:rPr><w:b/><w:color w:val="FF0000"/><w:sz w:val="24"/></w:rPr>
    <w:t>*** CRITICAL ***</w:t></w:r></w:p>

  <w:p/>

  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>${checkbox}</w:t></w:r>
    <w:r><w:rPr><w:b/><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">  PI POWER IS PLUGGED BACK IN</w:t></w:r></w:p>

  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>${checkbox}</w:t></w:r>
    <w:r><w:rPr><w:b/><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">  PI ORANGE AND GREEN ETHERNET LIGHTS ARE ON</w:t></w:r></w:p>

  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>${checkbox}</w:t></w:r>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">  Removed drive is labeled with date and initials</w:t></w:r></w:p>

  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>${checkbox}</w:t></w:r>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">  Close lid to enclosure</w:t></w:r></w:p>

  <w:p/>

  <!-- CAMERA CHECKS -->
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="32"/></w:rPr><w:t>CAMERA CHECKS</w:t></w:r></w:p>

  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>${checkbox}</w:t></w:r>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">  Check cables for wear or rodent damage</w:t></w:r></w:p>

  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>${checkbox}</w:t></w:r>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">  Check tripods and camera orientation</w:t></w:r></w:p>

  <w:p><w:pPr><w:ind w:left="360"/></w:pPr>
    <w:r><w:rPr><w:sz w:val="28"/></w:rPr><w:t>${checkbox}</w:t></w:r>
    <w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">  Wipe lenses carefully with provided lens wipes</w:t></w:r></w:p>

</w:body>
</w:document>
"@

$contentTypes = @"
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"@

$rels = @"
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>
"@

# Build .docx (which is a .zip)
$tempDir = Join-Path $env:TEMP "docx_build_$(Get-Random)"
New-Item -ItemType Directory -Path $tempDir -Force | Out-Null
New-Item -ItemType Directory -Path "$tempDir\_rels" -Force | Out-Null
New-Item -ItemType Directory -Path "$tempDir\word" -Force | Out-Null

$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText("$tempDir\[Content_Types].xml", $contentTypes, $utf8NoBom)
[System.IO.File]::WriteAllText("$tempDir\_rels\.rels", $rels, $utf8NoBom)
[System.IO.File]::WriteAllText("$tempDir\word\document.xml", $body, $utf8NoBom)

# Remove existing file if present
if (Test-Path $outPath) { Remove-Item $outPath -Force }

# Create zip
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory($tempDir, $outPath)

# Cleanup
Remove-Item $tempDir -Recurse -Force

Write-Host "Created: $outPath"
