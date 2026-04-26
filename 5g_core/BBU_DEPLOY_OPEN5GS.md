### 1) Cloning the repository

```plaintext
 git clone https://github.com/IANG-5G-LAB/5G-Core-Network.git
```


### 2) Environment initialization

The first step is initialize the core functions

```plaintext
cd Scenario_5

#Run the core without logs
make start-5g-core

#Run the core with logs
make start-5g-core-debug
```
after this: enable the fowarding tables: 
```plaintext
make enable-forward
```


And then check if the device that you want to connect is already registered on the hss.

### 3) Populating HSS

**The follow configuration is shared between the 4G and the 5G.**

Open ([http://\<DOCKER_HOST_IP](http://\<DOCKER_HOST_IP)\\>:9999) in a web browser, where \<DOCKER_HOST_IP\> is the IP of the machine/VM running the open5gs containers. Login with following credentials

```plaintext
Username : admin
Password : 1423
```

Then, create a network profile.

#### 3.1) Creating Network Profile

Go to the left side menu and click in the profile button. In the right corner, click in the plus symbol and type as follows:

- Title: CinRDS
- Profile Key (K): 6874736969202073796d4b2079650a73
- Operator Key (OPc/OP): 8b7645883644923debfadb824021f087
- APN information:
  - internet
    - type: IPv4
    - 5QI/QCI: 9
    - ARP Priority Level (1-15): 8
    - Downlink: 1 Gbps
    - Uplink: 1 Gbps
  - ims
    - type: IPv4
    - 5QI/QCI: 5
    - ARP Priority Level (1-15): 1
    - Downlink: 3850 Kbps
    - Uplink: 1530 Kbps
    - PCC Rule1:
      - 5QI/QCI: 1
      - ARP Priority Level (1-15): 2
      - Capability: enabled
      - Vulnerability: enabled
      - MBR Downlink/Uplink: 128 Kbps
      - GBR Downlink/Uplink: 128 Kbps
    - PCC Rule2:
      - 5QI/QCI: 2
      - ARP Priority Level (1-15): 4
      - Capability: enabled
      - Vulnerability: enabled
      - MBR Downlink/Uplink: 128 Kbps
      - GBR Downlink/Uplink: 128 Kbps


After saving, you can register your device in the network.


#### 3.2) Registering Device in the Network

In the subscriber button, on the left side menu, click in the add button and type as follows:

**IMPORTANT**: before starting the process, make sure you are creating a subscriber with the right network profile, because it can chance all the parameters that were set above.

- Sim Card IMSI
- Sim Card MSISDN

Remainder: you can check the infos above in the phone information section, on the smartphone secret menu. To access it, type `*#*#4636#*#*` and hit the call button.

After fulfilling this fields, click in save.