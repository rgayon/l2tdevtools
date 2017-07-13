# Avoid re-running on reboot.
if (Test-Path -Path $data_directory) {
    Write-Host 'Tools already present, exiting startup script.'
    exit
}

## Set up default URLs and Paths
$data_directory = 'C:\data\'
$install_log_path = "$($data_directory)\provision.log"
$jenkins_home_directory = 'C:\jenkins'
$jenkins_slave_url = 'https://plaso-ci.deerpie.com/jenkins/jnlpJars/slave.jar'

$jenkins_slave_path = "$(jenkins_home_directory)\slave.jar"
$vc_for_python_url = 'https://download.microsoft.com/download/7/9/6/796EF2E4-801B-4FC4-AB28-B59FBF6D907B/VCForPython27.msi'
$vc_for_python_path = "$($data_directory)\VCForPython27.msi"
$vs_registry_key_path = 'HKLM:\Software\Wow6432Node\Microsoft\VisualStudio\9.0\Setup\VC'
$vs_registry_key_value = "C:\Users\$($username)\AppData\Local\Programs\Common\Microsoft\Visual C++ for Python\9.0"

$ssh_user_directory = "C:\Users\$($username)\.ssh"
$authorized_keys_path = "$($ssh_user_directory)\authorized_keys"

## Do the things

mkdir $data_directory >> $provision

## Download & install Visual Studio for Python
echo "Downloading $($vc_for_python_url) to $($vc_for_python_path)" >> $provision
(New-Object System.Net.WebClient).DownloadFile($vc_for_python_url, $vc_for_python_path)
echo 'Download complete, now installing'  >> $provision
$msiexec_arguments=@"
/i $($vc_for_python_path) ROOT="$($vs_registry_key_value)" /qn /log $($provision)
"@
Start-Process msiexec.exe -Wait -ArgumentList $msiexec_arguments
echo "Adding registry key $($vs_registry_key_path)\productdir with value $($vs_registry_key_value)" >> $provision
New-Item $vs_registry_key_path -Force | New-ItemProperty -Name productdir -Value $vs_registry_key_value -Force
echo 'Installing Microsoft Visual C++ Compiler for Python 2.7... done!' >> $provision

## Download & install Chocolatey
echo 'Installing Chocolatey' >> $provision
iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))

## Install plaso dependencies
Choco install patch -y >> $provision # Used when building plaso dependencies
Choco install jre8 -y >> $provision   # Needed for jenkins client
Choco install git -y >> $provision
Choco install python2 -y >> $provision

pip.exe install wmi >> $provision
pip.exe install pypiwin32  >> $provision

## Set up SSHd
echo 'Installing SSHd' >> $provision
Choco install openssh -y --force --params '"/SSHServerFeature"' >> $provision
echo "Write public key to $($authorized_keys_path) file" >> $provision
mkdir $ssh_user_directory
$pub_key_content >> $authorized_keys_path
echo 'Give read access to SSHd' >> $provision
$Acl = Get-Acl $authorized_keys_path
$Ar = New-Object system.security.accesscontrol.filesystemaccessrule("NT SERVICES\sshd","Read","Allow")
$Acl.SetAccessRule($Ar)
Set-Acl $authorized_keys_path $Acl
echo "New ACLs for $($authorized_keys_path):" >> $provision
Get-Acl $authorized_keys_path >> $provision

echo 'Downloading Jenkins client'  >> $provision
mkdir $jenkins_home_directory
(New-Object System.Net.WebClient).DownloadFile($jenkins_slave_url, $jenkins_slave_path)

