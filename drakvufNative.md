# Inštalácia DRAKVUF Sandbox (natívny Xen)

## Návod pre Debian 12 na bare-metal hardvéri

---


> **Rozdiel oproti nested virtualizácii:** Pri tomto prístupe Xen beží priamo na hardvéri (nie vnútri KVM VM).

---
## 1. Inštalácia Debian 12

Nainštalujte Debian 12 Bookworm v minimálnej konfigurácii. Inštalačný ISO obraz `debian-12.13.0-amd64-netinst.iso` je priložený ako príloha k tomuto návodu.

- **Partitioning:** Guided – use entire disk → All files in one partition
- **Software selection:** iba SSH server + standard system utilities
- **GRUB:** nainštalovaný na primárny disk

Po inštalácii overte verziu systému:
```bash
cat /etc/debian_version
# 12.x
```
---

## 2. Overenie procesora

```bash
grep -m1 flags /proc/cpuinfo | tr ' ' '\n' | grep -E '^(vmx|ept)$'
```

Výstup musí obsahovať oba riadky:
```
vmx
ept
```

---

## 3. Stiahnutie DRAKVUF balíkov

```bash
sudo mkdir -p /opt/drakvuf-debs
cd /opt/drakvuf-debs

sudo apt install -y wget jq curl

# Zobraziť dostupné balíky z najnovšieho releasu
curl -sL https://api.github.com/repos/tklengyel/drakvuf-builds/releases/latest \
  | jq -r '.assets[].browser_download_url'

# Stiahnuť balíky pre Debian Bookworm
sudo wget https://github.com/tklengyel/drakvuf-builds/releases/download/build-cb6213981f71fd3f70c30860e81744b91011dd4e/xen-hypervisor-4.20.1-debian-bookworm-amd64.deb

sudo wget https://github.com/tklengyel/drakvuf-builds/releases/download/build-cb6213981f71fd3f70c30860e81744b91011dd4e/drakvuf-bundle-1.1-cb62139-debian-bookworm.deb

# Overiť stiahnuté súbory
ls -lh /opt/drakvuf-debs/
# xen-hypervisor-4.20.1-debian-bookworm-amd64.deb    90M
# drakvuf-bundle-1.1-cb62139-debian-bookworm.deb     3.9M
```

---

## 4. Inštalácia Xen hypervízora

```bash
cd /opt/drakvuf-debs
sudo apt install -y ./xen-hypervisor-4.20.1-debian-bookworm-amd64.deb
```

Inštalátor automaticky:
- Nakonfiguruje GRUB — Xen bude defaultný bootovací hypervízor
- Nastaví DRAKVUF-optimalizované parametre (`force-ept=1`, `altp2m=1`, `ept=ad=0`)
- Pridelí dom0 pamäť a CPU jadrá

Kľúčový výstup:
```
Using DRAKVUF-optimized settings for Xen
Intel EPT is supported by your CPU
WARNING: GRUB_DEFAULT changed to boot into Xen by default!
```

---

## 5. Inštalácia DRAKVUF enginu

```bash
cd /opt/drakvuf-debs
sudo apt install -y ./drakvuf-bundle-1.1-cb62139-debian-bookworm.deb
```

---

## 6. Reboot do Xen

```bash
sudo reboot
```

Po reboote server nabootuje cez Xen. Prihláste sa a overte:

```bash
sudo xl info | grep xen_version
# xen_version            : 4.20.1

sudo xl list
# Name         ID  Mem VCPUs State  Time(s)
# Domain-0      0 3072     2 r-----   11.4
```

Overte DRAKVUF CLI nástroje:

```bash
which drakvuf injector vmi-win-guid vmi-win-offsets vmi-process-list
# /usr/bin/drakvuf
# /usr/bin/injector
# /usr/bin/vmi-win-guid
# /usr/bin/vmi-win-offsets
# /usr/bin/vmi-process-list
```

---

## 7. Inštalácia DRAKVUF Sandbox (Python wrapper)

```bash
sudo apt install -y iptables tcpdump dnsmasq qemu-utils \
  bridge-utils libmagic1 python3-venv redis-server

sudo python3 -m venv /opt/venv
sudo /opt/venv/bin/pip install --upgrade pip setuptools wheel
sudo /opt/venv/bin/pip install drakvuf-sandbox

# Overiť inštaláciu
source /opt/venv/bin/activate
drakrun --help
```

---

## 8. Príprava Windows 7 ISO

Windows 7 SP1 x64 ISO je potrebné získať samostatne. Odporúčaná verzia: `Windows 7 Ultimate SP1 x64`.

Skopírujte ISO na server napr. cez SCP:

```bash
# Z iného počítača
scp win7_64_bit.iso user@<IP_SERVERA>:/home/user/
```

---

## 9. Oprava audio konfigurácie

```bash
sudo sed -i "s/^audio = 1/#audio = 1/" /etc/drakrun/cfg.template
sudo sed -i "s/^soundhw=/#soundhw=/" /etc/drakrun/cfg.template

# Overiť zmenu
grep "audio\|sound" /etc/drakrun/cfg.template
# #audio = 1
# #soundhw='hda'
```

---

## 10. Inštalácia Windows 7 VM

```bash
source /opt/venv/bin/activate

sudo /opt/venv/bin/drakrun install \
  --memory 2048 \
  --vcpus 2 \
  --disk-size 40G \
  ~/win7_64_bit.iso
```

> **Poznámka:** Na natívnom Xen môžete dať Windows VM viac pamäte a vCPU než pri nested verzii. Odporúčame 2–4 GB RAM a 2 vCPU.

Výstup:
```
Initial VM setup is complete and the vm-0 was launched.
Please now VNC to the port 5900 on this machine.
Your configured VNC password is: xxxxxxxx
```

Pripojenie na VNC (z iného PC v sieti alebo cez SSH tunel):

```bash
# Cez SSH tunel ak nemáte priamy prístup k portu 5900
ssh -L 5900:localhost:5900 user@<IP_SERVERA>
vncviewer 127.0.0.1:5900
```

### Postup inštalácie Windows 7

1. Zvoliť jazyk, čas, klávesnicu → **Next**
2. **Install now**
3. Prijať licenciu → **Next**
4. **Custom (advanced)**
5. Zvoliť disk (~40 GB) → **Next**
6. Počkať na inštaláciu (~15–20 minút na natívnom Xen)
7. Po reboote sa VNC odpojí — znovu pripojiť s rovnakým heslom
8. Zadať meno používateľa, heslo nechať **prázdne**
9. Product key → **Skip**
10. Windows Update → **Ask me later**
11. Network location → **Public network**
12. Po dokončení setup-u sa zobrazí **Windows 7 desktop**

---

## 11. Post-inštalácia a VMI profily

Po zobrazení Windows desktopu:

```bash
source /opt/venv/bin/activate
sudo /opt/venv/bin/drakrun postinstall
```

Úspešný výstup:
```
[INFO] All right, VM setup is done.
```

---

## 12. Spustenie DRAKVUF Sandbox

```bash
source /opt/venv/bin/activate

# Worker
sudo /opt/venv/bin/drakrun worker --vm-id 1 &

# Webové rozhranie
sudo /opt/venv/bin/python -m flask \
  --app drakrun.web.app:app run \
  --with-threads --host 0.0.0.0 --port 5000 &
```

Webové rozhranie je dostupné na:
```
http://<IP_SERVERA>:5000
```



---

## 13. Konfigurácia Karton mikroslužby na hlavnom serveri

Karton mikroservisa `karton_drakvuf_consumer.py` beží na hlavnom serveri (kde beží Karton Playground, CAPE a Cuckoo 3), nie na DRAKVUF serveri. Stačí zmeniť URL adresu v konfigurácii:

```python
# V karton_drakvuf_consumer.py zmeňte
self.drakvuf_base = "http://<IP_DRAKVUF_SERVERA>:5000"
```

Tým mikroservisa posiela vzorky na vzdialený DRAKVUF server cez REST API, zatiaľ čo výsledky ukladá do lokálneho MWDB.


## Prehľad portov

| Port | Služba |
|------|--------|
| 5000 | DRAKVUF web UI |
| 5900 | VNC – Windows VM (počas inštalácie) |
| 6379 | Redis (DRAKVUF) |
| 22 | SSH |