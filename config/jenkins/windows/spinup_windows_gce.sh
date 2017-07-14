#!/bin/bash

# This script spins up a new GCE Windows VM, and installs everything required
# to install the Jenkins agent and plaso build/testing dependencies

base_startup_script="install_windows_gce_choco.ps1"
identifier="$(pwgen 6)"
install_directory="C:\\data"
jenkins_home_directory="C:\\jenkins"
jenkins_master_gce="jenkins-master-4"
jenkins_slave_url="https://plaso-ci.deerpie.com/jenkins/jnlpJars/slave.jar"
machine_type="n1-standard-1"
machine_name="windows-2016-2"
project="plaso-ci"
startup_script="${identifier}-${base_startup_script}"
username="plaso_test"
zone="europe-west1-d"

echo "Creating SSH Key pair for this machine"
ssh-keygen -t rsa -b 1024 -N "" -f "id_rsa_${machine_name}" -C "jenkins"

echo "Customizing startup script"
cat >> "${startup_script}" <<CONFIG
\$username='${username}'
\$data_directory='${install_directory}'
\$jenkins_home_directory='${jenkins_home_directory}'
\$jenkins_slave_url = '${jenkins_slave_url}'
\$pub_key_content = @"
$(cat id_rsa_${machine_name}.pub)
"@
CONFIG

cat "${base_startup_script}" >> "${startup_script}"

echo "Creating instance $machine_name"
gcloud compute instances create "$machine_name" \
  --project "$project" \
  --zone "$zone" \
  --machine-type "$machine_type" \
  --network "default" \
  --scopes "storage-rw" \
  --image "https://www.googleapis.com/compute/v1/projects/windows-cloud/global/images/windows-server-2016-dc-v20170615" \
  --boot-disk-type "pd-standard" \
  --boot-disk-device-name "${machine_name}-disk" \
# We can't do that because set up requires dropping files in the user's
# directory, which is not created until first real login through RDP.
#  --metadata-from-file windows-startup-script-ps1=${startup_script}
#  --metadata-from-file sysprep-specialize-script-ps1=${pre_boot_script}

echo "Pushing SSH private key to ${jenkins_master_gce}"
gcloud compute scp --project ${project} --zone ${zone} "id_rsa_${machine_name}" ${jenkins_master_gce}:/tmp/
gcloud compute ssh --project ${project} --zone ${zone} ${jenkins_master_gce} -- sudo mv "/tmp/id_rsa_${machine_name}" /var/lib/jenkins/.ssh/
gcloud compute ssh --project ${project} --zone ${zone} ${jenkins_master_gce} -- sudo chown jenkins:jenkins "/var/lib/jenkins/.ssh/id_rsa_${machine_name}"
gcloud compute ssh --project ${project} --zone ${zone} ${jenkins_master_gce} -- sudo chmod 600 "/var/lib/jenkins/.ssh/id_rsa_${machine_name}"

read -r -a ips <<< $(gcloud --format 'get(INTERNAL_IP,EXTERNAL_IP)' compute instances list --project ${project} ${machine_name})
gce_internal_ip=${ips[0]}
gce_external_ip=${ips[1]}

echo "Done. Waiting a bit for the machine to be ready, and update credentials"
sleep 30
echo "Setting RDP Credentials for user ${username} on instance ${machine_name}"
gcloud compute reset-windows-password --user "${username}" \
  --zone "$zone" \
  --project "$project" \
  --quiet \
  ${machine_name}


cat <<INFOHELP
* Create a new windows Jenkins node:
    Remote root directory: ${jenkins_home_directory}
    Launch method: Via execution of command on the master
    Launch command:
      ssh -i /var/lib/jenkins/.ssh/id_rsa_${machine_name} -l ${username} ${gce_internal_ip} "\"java.exe\" " -jar "\"${jenkins_home_directory}\\slave.jar\""
    Tools:
      Git path:
        C:\\Program Files\\Git\\bin\\git.exe
* Please access your new VM with RDP (with the password displayed earlier):
    xfreerdp --plugin cliprdr -u ${username} ${gce_external_ip}
  And execute ${startup_script} in a admin Powershell prompt.
INFOHELP
