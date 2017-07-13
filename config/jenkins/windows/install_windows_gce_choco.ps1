# Avoid re-running on reboot.
if (Test-Path -Path $data_directory) {
    Write-Host 'Tools already present, exiting startup script.'
    exit
}

$data_directory = 'C:\data\'
$jenkins_home_directory = 'C:\jenkins'
$jenkins_slave_url = 'https://plaso-ci.deerpie.com/jenkins/jnlpJars/slave.jar'

$jenkins_slave_path = "$(jenkins_home_directory)\slave.jar"
$vc_for_python_url = 'https://download.microsoft.com/download/7/9/6/796EF2E4-801B-4FC4-AB28-B59FBF6D907B/VCForPython27.msi'
$vc_for_python_path = "$($data_directory)\VCForPython27.msi"
$vs_registry_key_path = 'HKLM:\Software\Wow6432Node\Microsoft\VisualStudio\9.0\Setup\VC'
$vs_registry_key_value = "C:\Users\$($username)\AppData\Local\Programs\Common\Microsoft\Visual C++ for Python\9.0"

$ssh_user_directory = "C:\Users\$($username)\.ssh"
$authorized_keys_path = "$($ssh_user_directory)\authorized_keys"


mkdir $data_directory

Write-Host "Downloading $($vc_for_python_url) to $($vc_for_python_path)"
(New-Object System.Net.WebClient).DownloadFile($vc_for_python_url, $vc_for_python_path)
Write-Host 'Download complete, now installing'
$msiexec_arguments=@"
/i $($vc_for_python_path) ROOT="$($vs_registry_key_value)" /qn /log C:\log.txt
"@
Start-Process msiexec.exe -Wait -ArgumentList $msiexec_arguments
Write-Host 'Installing Microsoft Visual C++ Compiler for Python 2.7... done!'

Write-Host "Adding registry key $($vs_registry_key_path)\productdir with value $($vs_registry_key_value)"
New-Item $vs_registry_key_path -Force | New-ItemProperty -Name productdir -Value $vs_registry_key_value -Force

# Install Chocolatey
iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))

Choco install patch -y
Choco install jre8 -y
Choco install git -y
Choco install python2 -y

pip.exe install wmi
pip.exe install pypiwin32

## Set up SSH
# Instal sshd
Choco install openssh -y --force --params '"/SSHServerFeature"'
# Write public key to authorized_keys file and set read access to SSHD
mkdir $ssh_user_directory
$pub_key_content >> $authorized_keys_path
$Acl = Get-Acl $authorized_keys_path
$Ar = New-Object system.security.accesscontrol.filesystemaccessrule("NT SERVICES\sshd","Read","Allow")
$Acl.SetAccessRule($Ar)
Set-Acl $authorized_keys_path $Acl

# Downloading Jenkins client
mkdir $jenkins_home_directory
(New-Object System.Net.WebClient).DownloadFile($jenkins_slave_url, $jenkins_slave_path)

