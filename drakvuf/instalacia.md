# Inštalácia DRAKVUF Sandbox v nested virtualizácii (KVM → Xen → Windows)

## Kompletný návod pre Ubuntu 24.04 s existujúcim KVM prostredím

---

## Predpoklady
Všetky príkazy označené `[HOST]` sa spúšťajú na hostiteľskom Ubuntu.
Všetky príkazy označené `[DRAKVUF-HOST VM]` sa spúšťajú vo vnútri Debian VM cez SSH.

---

## 1. Overenie hostiteľského systému

**[HOST]** Overenie podpory nested virtualizácie:

```bash
cat /sys/module/kvm_intel/parameters/nested
```

Výstup musí byť `Y`. Ak nie, zapnite nested:

```bash
sudo modprobe -r kvm_intel
sudo modprobe kvm_intel nested=1
echo "options kvm_intel nested=1" | sudo tee /etc/modprobe.d/kvm.conf
```

---

## 2. Stiahnutie Debian 12 ISO

**[HOST]** DRAKVUF Sandbox oficiálne podporuje Debian 12 Bookworm:

```bash
cd ~/Downloads
wget https://cdimage.debian.org/cdimage/archive/12.13.0/amd64/iso-cd/debian-12.13.0-amd64-netinst.iso

# Presunúť ISO do libvirt adresára
sudo cp ~/Downloads/debian-12.13.0-amd64-netinst.iso \
  /var/lib/libvirt/images/
sudo chmod 644 \
  /var/lib/libvirt/images/debian-12.13.0-amd64-netinst.iso
```

---

## 3. Vytvorenie Debian 12 VM (drakvuf-host)

**[HOST]** Vytvorenie diskového obrazu a spustenie inštalácie:

```bash
# Vytvorenie diskového obrazu (40 GB)
sudo qemu-img create -f qcow2 \
  /var/lib/libvirt/images/drakvuf-host.qcow2 40G

# Vytvorenie VM - KRITICKÝ parameter: --cpu host-passthrough
# zabezpečuje že VM vidí VT-x a EPT flagy procesora
sudo virt-install \
  --name drakvuf-host \
  --ram 4096 \
  --vcpus 2 \
  --cpu host-passthrough,check=none \
  --disk path=/var/lib/libvirt/images/drakvuf-host.qcow2,bus=virtio \
  --os-variant debian12 \
  --network network=default,model=virtio \
  --graphics vnc,listen=127.0.0.1,port=5902 \
  --cdrom /var/lib/libvirt/images/debian-12.13.0-amd64-netinst.iso \
  --features kvm_hidden=on \
  --noautoconsole
```

**[HOST]** Pripojenie na inštalátor cez VNC:

```bash
# Overiť že VM beží
sudo virsh list --all
# Výstup: drakvuf-host    running

# Pripojiť sa na VNC (port 5902)
vncviewer 127.0.0.1:5902
```

### Postup inštalácie Debian 12 cez VNC inštalátor

V grafickom inštalátore nastavte:

| Pole | Hodnota |
|------|---------|
| Language | English |
| Hostname | `drakvuf-host` |
| Domain | (prázdne) |
| Root password | ľubovoľné, zapamätajte si |
| Username | `drakvuf` |
| User password | ľubovoľné, zapamätajte si |
| Partitioning | Guided – use entire disk → All files in one partition |
| Mirror | deb.debian.org |
| HTTP proxy | (prázdne) |
| Popularity contest | No |
| Software selection | **iba SSH server + standard system utilities** |
| GRUB | Yes → /dev/vda |

Po dokončení inštalácie sa VM reštartuje a nabootuje do Debianu.

---

## 4. Pripojenie na VM cez SSH

**[HOST]** Zistenie IP adresy VM:

```bash
# Po reštarte VM overiť že beží
sudo virsh list --all
# Výstup: drakvuf-host    running

# Zistiť IP adresu VM
sudo virsh domifaddr drakvuf-host
# Príklad výstupu:
# Name     MAC address         Protocol  Address
# vnet0    52:54:00:xx:xx:xx   ipv4      192.168.122.162/24
```

IP adresa bude z rozsahu `192.168.122.0/24` (štandardná libvirt sieť).

**[HOST]** Prvé pripojenie cez SSH:

```bash
ssh drakvuf-host@192.168.122.162
# Pri prvom pripojení potvrdiť fingerprint: yes
# Heslo: to čo ste zadali pri inštalácii
```

Od tohto bodu pracujeme v SSH session — VNC môžete zatvoriť.

---

## 5. Príprava VM — sudo a overenie nested virtualizácie

**[DRAKVUF-HOST VM]** Pridanie používateľa do sudoers:

```bash
# Prepnúť na root
su -
# Zadať root heslo

# Pridať drakvuf do skupiny sudo
apt install -y sudo
usermod -aG sudo drakvuf
exit

# Odhlásiť sa a znovu prihlásiť aby sa zmena skupiny prejavila
exit
```

**[HOST]** Znovu pripojiť:

```bash
ssh drakvuf-host@192.168.122.162
```

**[DRAKVUF-HOST VM]** Overenie nested virtualizácie — kritický krok:

```bash
grep -m1 flags /proc/cpuinfo | tr ' ' '\n' | grep -E '^(vmx|ept)$'
```

Výstup **musí** obsahovať oba riadky:
```
vmx
ept
```

Ak chýba niektorý z flagov, VM nebola vytvorená s `host-passthrough` CPU a Xen vnútri nebude fungovať.

---

## 6. Stiahnutie DRAKVUF balíkov
**[DRAKVUF-HOST VM]** Potrebné balíky sú dostupné na stránke releasov projektu [drakvuf-builds](https://github.com/tklengyel/drakvuf-builds/releases) a zároveň sú priložené ako príloha k tomuto návodu.

Vytvorenie adresára a príprava balíkov:
```bash
sudo mkdir -p /opt/drakvuf-debs
cd /opt/drakvuf-debs
# Nainštalovať wget a jq pre stiahnutie
sudo apt install -y wget jq curl
```

**Možnosť A – Stiahnutie z GitHubu:**
```bash
# Zobraziť dostupné balíky z najnovšieho releasu
curl -sL https://api.github.com/repos/tklengyel/drakvuf-builds/releases/latest \
  | jq -r '.assets[].browser_download_url'
# Stiahnuť balíky pre Debian Bookworm
sudo wget https://github.com/tklengyel/drakvuf-builds/releases/download/build-cb6213981f71fd3f70c30860e81744b91011dd4e/xen-hypervisor-4.20.1-debian-bookworm-amd64.deb
sudo wget https://github.com/tklengyel/drakvuf-builds/releases/download/build-cb6213981f71fd3f70c30860e81744b91011dd4e/drakvuf-bundle-1.1-cb62139-debian-bookworm.deb
```

**Možnosť B – Použitie balíkov priložených k návodu:**
Skopírovať priložené `.deb` súbory do adresára `/opt/drakvuf-debs/`.

```bash
# Overiť že oba súbory sú v adresári
ls -lh /opt/drakvuf-debs/
# xen-hypervisor-4.20.1-debian-bookworm-amd64.deb    90M
# drakvuf-bundle-1.1-cb62139-debian-bookworm.deb     3.9M
```
---

## 7. Inštalácia Xen hypervízora

**[DRAKVUF-HOST VM]** Inštalácia Xen zo stiahnutého balíka:

```bash
cd /opt/drakvuf-debs
sudo apt install -y ./xen-hypervisor-4.20.1-debian-bookworm-amd64.deb
```

Inštalátor automaticky nakonfiguruje GRUB a nastaví Xen ako defaultný bootovací hypervízor. Kľúčový výstup inštalátora:

```
Using DRAKVUF-optimized settings for Xen
Intel EPT is supported by your CPU
WARNING: GRUB_DEFAULT changed to boot into Xen by default!
```

---

## 8. Inštalácia DRAKVUF enginu

**[DRAKVUF-HOST VM]**

```bash
cd /opt/drakvuf-debs
sudo apt install -y ./drakvuf-bundle-1.1-cb62139-debian-bookworm.deb
```

---

## 9. Reboot VM do Xen módu

**[DRAKVUF-HOST VM]** Reštartovanie VM:

```bash
sudo reboot
```

SSH session sa ukončí. VM sa reštartuje a tentokrát nabootuje cez Xen hypervízor (GRUB nastavil Xen ako default).

**[HOST]** Počkajte 30–60 sekúnd a znovu sa pripojte:

```bash
ssh drakvuf-host@192.168.122.162
```

**[DRAKVUF-HOST VM]** Overenie že Xen beží:

```bash
sudo xl info | grep xen_version
# xen_version            : 4.20.1

sudo xl list
# Name         ID  Mem VCPUs State  Time(s)
# Domain-0      0 1957     1 r-----   11.4
```

Ak `xl info` funguje a zobrazuje verziu Xen, hypervízor beží správne.

**[DRAKVUF-HOST VM]** Overenie DRAKVUF CLI nástrojov:

```bash
which drakvuf injector vmi-win-guid vmi-win-offsets vmi-process-list
# /usr/bin/drakvuf
# /usr/bin/injector
# /usr/bin/vmi-win-guid
# /usr/bin/vmi-win-offsets
# /usr/bin/vmi-process-list
```

---

## 10. Inštalácia DRAKVUF Sandbox (Python wrapper)

**[DRAKVUF-HOST VM]** Systémové závislosti a Python venv:

```bash
sudo apt install -y iptables tcpdump dnsmasq qemu-utils \
  bridge-utils libmagic1 python3-venv redis-server

sudo python3 -m venv /opt/venv
sudo /opt/venv/bin/pip install --upgrade pip setuptools wheel
sudo /opt/venv/bin/pip install drakvuf-sandbox

# Aktivovať venv
source /opt/venv/bin/activate

# Overiť inštaláciu
drakrun --help
```

---

## 11. Príprava Windows 7 ISO

Windows 7 SP1 x64 ISO je potrebné získať samostatne (napr. z archívu). Odporúčaná verzia: `Windows 7 Ultimate SP1 x64`.

**[HOST]** Skopírovanie ISO do VM:

```bash
# Najprv skopírovať ISO na hostiteľa ak ho nemáte
# Potom preniesť do VM cez SCP
scp ~/Downloads/win7_64_bit.iso drakvuf@192.168.122.162:/home/drakvuf/
```

---

## 12. Oprava audio konfigurácie

**[DRAKVUF-HOST VM]** Pred spustením inštalácie Windows je potrebné vypnúť audio v šablóne konfigurácie, inak QEMU padá s chybou `no default audio driver available`:

```bash
sudo sed -i "s/^audio = 1/#audio = 1/" /etc/drakrun/cfg.template
sudo sed -i "s/^soundhw=/#soundhw=/" /etc/drakrun/cfg.template

# Overiť zmenu
grep "audio\|sound" /etc/drakrun/cfg.template
# #audio = 1
# #soundhw='hda'
```

---

## 13. Inštalácia Windows 7 VM

**[DRAKVUF-HOST VM]** Spustenie inštalácie:

```bash
source /opt/venv/bin/activate

sudo /opt/venv/bin/drakrun install \
  --memory 1536 \
  --vcpus 1 \
  --disk-size 15G \
  ~/win7_64_bit.iso
```

Výstup bude obsahovať VNC heslo a port:
```
Initial VM setup is complete and the vm-0 was launched.
Please now VNC to the port 5900 on this machine to perform Windows installation.
Your configured VNC password is: xxxxxxxx
```

**[HOST]** Pripojenie na Windows inštalátor:

```bash
# Port 5900 je na IP adrese VM (nie hostiteľa)
vncviewer 192.168.122.162:5900
# Zadať VNC heslo z predchádzajúceho výstupu
```

### Postup inštalácie Windows 7

1. Zvoliť jazyk, čas, klávesnicu → **Next**
2. **Install now**
3. Prijať licenciu → **Next**
4. **Custom (advanced)** — nie Upgrade
5. Zvoliť disk (~15 GB) → **Next**
6. Počkať na inštaláciu — v nested prostredí trvá **20–40 minút**
7. Po reboote sa VNC odpojí — znovu sa pripojiť s rovnakým heslom
8. Zadať meno používateľa (napr. `analyst`), heslo nechať **prázdne**
9. Product key preskočiť → **Skip**
10. Windows Update → **Ask me later**
11. Network location → **Public network**
12. Po dokončení setup-u sa zobrazí **Windows 7 desktop**

---

## 14. Post-inštalácia a VMI profily

**[DRAKVUF-HOST VM]** Po dokončení inštalácie Windows a zobrazení desktopu spustiť postinstall:

```bash
source /opt/venv/bin/activate
sudo /opt/venv/bin/drakrun postinstall
```


Úspešný výstup na konci:
```
[INFO] All right, VM setup is done.
```

---

## 15. Spustenie DRAKVUF Sandbox

**[DRAKVUF-HOST VM]** Spustenie workeru a webového rozhrania:

```bash
source /opt/venv/bin/activate

# Worker pre spracovanie analýz
sudo /opt/venv/bin/drakrun worker --vm-id 1 &

# Webové rozhranie na porte 5000
sudo /opt/venv/bin/python -m flask \
  --app drakrun.web.app:app run \
  --with-threads --host 0.0.0.0 --port 5000 &
```

**[HOST]** Webové rozhranie je dostupné na:

```
http://192.168.122.162:5000
```

---
