attach-eni
==========

Description
-----------

This is a tool which attaches ENI(Elastic Network Interfaces) at a command line. 

Example
-------

    shell> sudo /usr/sbin/attach-eni
    Usage: attach-eni [options]
        -k, --access-key ACCESS_KEY
        -s, --secret-key SECRET_KEY
        -r, --region REGION
        -n, --network-if-id IF_ID
        -d, --device-index INDEX
        -i, --instance-id INSTANCE_ID
    shell> sudo /usr/sbin/attach-eni -n eni-XXXXXXXX
    shell> /sbin/ifconfig -a | grep eth1
    eth1      Link encap:Ethernet  HWaddr XX:XX:XX:XX:XX:XX
