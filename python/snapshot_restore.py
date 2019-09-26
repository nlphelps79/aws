import boto3
import time
import datetime
import pytz
import sys


def find_snapshot(volume_id) :
    VolumeId=volume_id
    utc = pytz.UTC
    starttime=datetime.datetime(1,1,1,tzinfo=utc)
    snapshots = client.describe_snapshots(
        Filters=[
        {
            'Name': 'volume-id',
            'Values': [
            VolumeId,
            ]
        },
        ]
    )

    for snap in snapshots['Snapshots']:
        if snap['StartTime'] > starttime:
            snap_id = snap['SnapshotId']
            starttime= snap['StartTime']
    print "Latest snapshot", snap_id
    return snap_id

def create_new_volume(snapshot_id, old_volume_id):
    Volume_old= old_volume_id
    volume_availability_zone = client.describe_volumes(
        Filters=[
        {
           'Name': 'volume-id',
           'Values': [
           Volume_old,
           ]
        },
        ]
    )
    AvailabilityZone_volume = volume_availability_zone['Volumes'][0]['AvailabilityZone']
    print "Availability Zone of Volume:",AvailabilityZone_volume

    creationresponse = client.create_volume(
      AvailabilityZone=AvailabilityZone_volume,
      SnapshotId=snapshot_id,
      VolumeType='gp2'
    )
    volume_id = creationresponse['VolumeId']
    count=0
    status=''
    while  ( status != 'available' ) :
      response = client.describe_volumes(
        Filters=[
          {
              'Name': 'volume-id',
              'Values': [
                  volume_id,
              ]
          },
        ]
      )
      status=response['Volumes'][0]['State']
      time.sleep(5)
      if (count > 60) :
          return 'failed to create volume'
      count=count+1
    new_volume_id = response['Volumes'][0]['VolumeId']
    print "New volume ID:", new_volume_id
    ec2 = session.resource('ec2', region_name='us-east-1')
    volume_for_tags = ec2.Volume(Volume_old)
    volume_tags = {}
    for tags in volume_for_tags.tags:
        volume_tags[tags['Key']] = tags['Value']
    
    for key in volume_tags:
        value = volume_tags[key]
        tags = ec2.create_tags(
         Resources=[new_volume_id],
         Tags=[{
                    "Key": key,
                    "Value": value
                }]
            )
    tags = ec2.create_tags(
      Resources=[Volume_old],
      Tags=[{
               'Key': 'Bad Volume',
               'Value': 'True', 
      }]
    ) 
    return new_volume_id



def detach_old_attach_new_volume(instance_id) :
    
    #list all volumes
    response=client.describe_instances(
        Filters=[
            {
                'Name': 'instance-id',
                'Values': [
                    instance_id,
                ]
            },
        ],
    )
    device_name = response['Reservations'][0]['Instances'][0]['RootDeviceName']
    for volume in response['Reservations'][0]['Instances'][0]['BlockDeviceMappings']:
        if volume['DeviceName'] == device_name:
            old_volume_id = volume['Ebs']['VolumeId']
    print "Root device:",device_name
    print "Restoring Volume:",old_volume_id
    #method calling for snapshot of latest snapshot
    if sys.argv[1] == 'previous_snap' :
        snapshot_id = find_snapshot(old_volume_id)
    elif sys.argv[1] == 'specific_snap' :
        snapshot_id = sys.argv[3]
        print "Specific snapshot", snapshot_id
    #Creating new volume using Snapshot ID and volume ID 
    new_volume_id   = create_new_volume(snapshot_id, old_volume_id)
    if (new_volume_id == 'failed') :
        print "new volume creation failed"
        exit (1)
    response = client.stop_instances(
        InstanceIds=[
            instance_id,
        ],
        Force=True
    )
    response=client.describe_instances(
        Filters=[
            {
                'Name': 'instance-id',
                'Values': [
                    instance_id,
                ]
            },
        ],
    )
    status = response['Reservations'][0]['Instances'][0]
    while (status['State']['Name'] != 'stopped') :
        time.sleep(10)
        response=client.describe_instances(
            Filters=[
                {
                    'Name': 'instance-id',
                    'Values': [
                        instance_id,
                    ]
                },
            ],
        )
        status = response['Reservations'][0]['Instances'][0]
    if status['State']['Name'] == 'stopped' :
        response = client.detach_volume(
        Device=device_name,
        Force=True,
        InstanceId=instance_id,
        VolumeId=old_volume_id
        )
    time.sleep(20)

    response = client.attach_volume(
      Device=device_name,
      InstanceId=instance_id,
      VolumeId=new_volume_id
    )
    response = client.start_instances(
      InstanceIds=[
          instance_id,
      ],
    )

if __name__ == '__main__':
    # initialize client connection to AWS
    session= boto3.Session(profile_name='sbx')
    client= session.client('ec2', region_name='us-east-1')

    if sys.argv[1] == 'previous_snap' :
        print("Single host rollbacks beginning")

        # Fetch all instances where Description tag = user input string
        arglist = []
        for arg in sys.argv[2:]:
          arglist.append(arg)
        
        for instance_ids in arglist:
            print(
              'Instance ID: ' +
              instance_ids +
              ' will be rolled back to previous snapshot'
              )
            detach_old_attach_new_volume(instance_ids)
    elif sys.argv[1] == 'specific_snap' :
        single_instance_id = sys.argv[2]
        print("Single host rollbacks beginning")
        print(
          'Instance ID: ' +
          single_instance_id +
          ' will be rolled back to specified snapshot'
          )
        detach_old_attach_new_volume(single_instance_id)
