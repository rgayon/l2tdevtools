$data_directory = 'C:\data\'

$username='plaso_test'

$vc_for_python_url = 'https://download.microsoft.com/download/7/9/6/796EF2E4-801B-4FC4-AB28-B59FBF6D907B/VCForPython27.msi'
$vc_for_python_path = "$($data_directory)\VCForPython27.msi"
$vs_registry_key_path = 'HKLM\Software\Wow6432Node\Microsoft\VisualStudio\9.0\Setup\VC'
$vs_registry_key_value = "C:\Users\$($username)\AppData\Local\Programs\Common\Microsoft\Visual C++ for Python\9.0"
$gnu_patch_url = 'https://netcologne.dl.sourceforge.net/project/gnuwin32/patch/2.5.9-7/patch-2.5.9-7-bin.zip'
$gnu_patch_path = "$($data_directory)\patch-2.5.9-7-bin.zip"
$gnu_patch_destination_directory = 'C:\Program Files (x86)\GnuWin32'
$gnu_patch_manifest_path = "$($data_directory)\manifest.mf"

# Avoid re-running on reboot.
if (Test-Path -Path $data_directory) {
    Write-Host 'Tools already present, exiting startup script.'
    exit
}

mkdir $data_directory

Write-Host "Downloading $($vc_for_python_url) to $($vc_for_python_path)"
wget $vc_for_python_url -OutFile $vc_for_python_path | Out-Null
msiexec /q /i $vc_for_python_path | Out-Null
Write-Host "Installing Microsoft Visual C++ Compiler for Python 2.7... done!"

Write-Host "Adding registry key $($vs_registry_key_path)\productdir with value $($vs_registry_key_value)"
New-Item $vs_registry_key_path -Force | New-ItemProperty -Name productdir -Value $vs_registry_key_value -Force | Out-Null

Add-Type -assembly "System.IO.Compression"
Add-Type -assembly "System.IO.Compression.Filesystem"
Write-Host "Downloading $($gnu_patch_url) to $($gnu_patch_path)"
wget $gnu_patch_url -OutFile $gnu_patch_path  | Out-Null
[System.IO.Compression.ZipFile]::ExtractToDirectory($gnu_patch_path, $gnu_patch_destination_directory)
$manifest = @"
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
<assemblyIdentity version="1.0.0.0" processorArchitecture="X86" name="patch.exe" type="win32"/>
<trustInfo xmlns="urn:schemas-microsoft-com:asm.v2">
<security>
<requestedPrivileges>
<requestedExecutionLevel level="asInvoker" uiAccess="false"/>
</requestedPrivileges>
</security>
</trustInfo>
</assembly>
"@

Write-Host 'Patching GNU Patch manifest...'
New-Item $gnu_patch_manifest_path -type file -force -value $manifest
# This will crash, but work...
& "$($vs_registry_key_value)\WinSDK\Bin\mt.exe" /manifest $gnu_patch_manifest_path /outputresource:$($gnu_patch_destination_directory)\Bin\patch.exe;#2 -ErrorAction SilentlyContinue  | Out-Null
Write-Host 'Installing Gnu Patch... done'




