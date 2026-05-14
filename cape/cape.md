# Inštalácia CAPE Sandbox na Ubuntu 24.04

## Kompletný návod s KVM Windows 10 x64

---

Všetky príkazy označené `[HOST]` sa spúšťajú na hostiteľskom Ubuntu 24.04.
Všetky príkazy označené `[CAPE-VM]` sa spúšťajú vo vnútri Windows 10 analytickej VM.

---

## 1. Overenie hostiteľského systému

**[HOST]** Overenie podpory hardvérovej virtualizácie:

```bash
grep -m1 -E '^(vmx|svm)$' <(grep -m1 flags /proc/cpuinfo | tr ' ' '\n')
```

Výstup musí obsahovať `vmx` (Intel) alebo `svm` (AMD). Ak chýba, povoľte virtualizáciu v BIOS/UEFI.


---

## 2. Inštalácia KVM a libvirt

**[HOST]** Inštalácia balíkov pre KVM virtualizáciu:

```bash
sudo apt-get update
sudo apt-get install -y qemu-kvm libvirt-daemon-system libvirt-clients \
  bridge-utils virt-manager libvirt-dev pkg-config python3-dev \
  tigervnc-viewer
```

**[HOST]** Pridanie používateľa do skupín a štart služby:

```bash
sudo usermod -aG libvirt $USER
sudo usermod -aG kvm $USER

sudo systemctl restart libvirtd
sudo systemctl enable libvirtd

# Aplikovať zmeny skupín bez odhlásenia
newgrp libvirt

# Overiť KVM
sudo kvm-ok
# Výstup: KVM acceleration can be used
```

Overenie že default libvirt sieť beží — CAPE bude komunikovať s VM cez `virbr0`:

```bash
sudo virsh net-list --all
# Name      State    Autostart   Persistent
# default   active   yes         yes

ip addr show virbr0 | grep inet
# inet 192.168.122.1/24 brd 192.168.122.255 scope global virbr0
```

---

## 3. Stiahnutie Windows 10 ISO

**[HOST]** Windows 10 x64 ISO je potrebné získať samostatne (napr. z Microsoft Media Creation Tool alebo archívu). Odporúčaná verzia: `Win10_22H2_EnglishInternational_x64v1.iso`.

Presunutie ISO do libvirt adresára:

```bash
sudo cp ~/Downloads/Win10_22H2_EnglishInternational_x64v1.iso \
  /var/lib/libvirt/images/
sudo chmod 644 \
  /var/lib/libvirt/images/Win10_22H2_EnglishInternational_x64v1.iso
```

---

## 4. Vytvorenie analytickej Windows 10 VM

**[HOST]** Vytvorenie diskového obrazu a spustenie inštalácie:

```bash
# Vytvorenie diskového obrazu (50 GB)
sudo qemu-img create -f qcow2 \
  /var/lib/libvirt/images/cape.qcow2 50G

# Vytvorenie VM
sudo virt-install \
  --name cape \
  --ram 2048 \
  --disk path=/var/lib/libvirt/images/cape.qcow2,size=50 \
  --vcpus 2 \
  --os-variant win10 \
  --network network=default \
  --graphics vnc,listen=127.0.0.1 \
  --cdrom /var/lib/libvirt/images/Win10_22H2_EnglishInternational_x64v1.iso \
  --noautoconsole
```

**[HOST]** Pripojenie na inštalátor cez VNC:

```bash
# Overiť že VM beží a zistiť VNC port
sudo virsh list --all
# Name   State
# cape   running

sudo virsh vncdisplay cape
# :0   (čo znamená port 5900)

# Nainštalovať VNC klient (ak ešte nie je)
sudo apt-get install -y tigervnc-viewer

vncviewer 127.0.0.1:5900
```

### Postup inštalácie Windows 10 cez VNC inštalátor

V grafickom inštalátore nastavte:

| Pole | Hodnota |
|------|---------|
| Language | English |
| Product key | **I don't have a product key** (skip) |
| Edícia | Windows 10 Pro |
| Typ inštalácie | **Custom: Install Windows only (advanced)** |
| Disk | Zvoliť celý 50 GB disk → Next |
| Region | English (anything) |
| Sieť | **I don't have internet** → **Continue with limited setup** |
| Účet | Lokálny účet, napr. `analyst`, **heslo nechať prázdne** |
| Privacy settings | Všetko vypnúť |

Po dokončení setup-u sa zobrazí Windows 10 desktop.

---

## 5. Konfigurácia Windows VM

**[CAPE-VM]** Vo vnútri Windows 10 desktopu vykonajte nasledujúce nastavenia.

### 5.1 Vypnutie Windows Defender a Firewallu

Otvorte **Windows Security** (Start → "Windows Security"):

- **Virus & threat protection** → **Manage settings** → vypnúť všetko (Real-time protection, Cloud-delivered protection, Automatic sample submission, Tamper Protection)
- **Firewall & network protection** → pre každý profil (Domain, Private, Public) → vypnúť firewall

### 5.2 Statická IP adresa

Otvorte **Control Panel → Network and Sharing Center → Change adapter settings**:

- Pravým klikom na sieťový adaptér → **Properties**
- Vybrať **Internet Protocol Version 4 (TCP/IPv4)** → **Properties**
- Nastaviť:
  - IP address: `192.168.122.101`
  - Subnet mask: `255.255.255.0`
  - Default gateway: `192.168.122.1`
  - Preferred DNS: `192.168.122.1`

### 5.3 Vypnutie Windows Update

Otvorte **services.msc** (Win+R → services.msc):

- Nájdite **Windows Update** → pravým klikom → **Properties**
- Startup type: **Disabled** → Stop → OK

Rovnako vypnite aj **Windows Update Medic Service** a **Update Orchestrator Service**.

---

## 6. Inštalácia Python 3.8 32-bit vo VM

**[CAPE-VM]** CAPE agent vyžaduje Python 3.8 32-bit (kvôli kompatibilite s analýzou 32-bit aj 64-bit vzoriek).

V Edge prehliadači stiahnite:

```
https://www.python.org/ftp/python/3.8.10/python-3.8.10.exe
```

Spustite inštalátor:

- **Customize installation**
- Zaškrtnúť **Add Python 3.8 to PATH**
- **Install for all users**
- Cestu nechať default (`C:\Python38-32\`)

Overenie v `cmd.exe`:

```cmd
python --version
REM Python 3.8.10
```

---

## 7. Inštalácia CAPE agenta vo VM

**[HOST]** Najprv pripravte CAPE repozitár na hostiteľovi:

```bash
cd ~
git clone https://github.com/kevoreilly/CAPEv2.git
```

**[HOST]** Spustenie HTTP servera na zdieľanie `agent.py`:

```bash
cd ~/CAPEv2/agent
python3 -m http.server 8000
```

Server beží na `http://192.168.122.1:8000/agent.py` (dostupný pre VM cez `virbr0`).

**[CAPE-VM]** V Edge prehliadači vo Windows otvorte:

```
http://192.168.122.1:8000/agent.py
```

Stiahnite súbor a uložte na `C:\Users\analyst\Desktop\agent.py`.

**[CAPE-VM]** Spustite agenta v `cmd.exe`:

```cmd
python C:\Users\analyst\Desktop\agent.py
```

Okno cmd musí ostať otvorené — agent počúva na porte `8000` a čaká na pripojenie z CAPE.

> **Poznámka:** Aby sa agent spúšťal automaticky po prihlásení, môžete vytvoriť skratku v `C:\Users\analyst\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\` ukazujúcu na `pythonw.exe C:\Users\analyst\Desktop\agent.py`.

**[HOST]** Overenie že agent reaguje:

```bash
curl http://192.168.122.101:8000/
# {"message": "CAPE Agent!", "version": "0.x", "features": [...]}
```

Ak `curl` vráti JSON odpoveď, agent vo VM komunikuje korektne.

---

## 8. Vytvorenie snapshotu

**[HOST]** Keď je vo VM spustený agent a všetko nakonfigurované, vytvorte snapshot — CAPE bude pred každou analýzou obnovovať VM práve do tohto stavu:

```bash
sudo virsh snapshot-create-as cape cape-agent-snapshot \
  "clean state with agent running"

# Overiť
sudo virsh snapshot-list cape
# Name                   Creation Time             State
# cape-agent-snapshot    2026-05-13 14:23:12 +0200 running
```

> **Dôležité:** Snapshot sa musí vytvoriť **kým VM beží** a agent je aktívny. Stav `running` v zozname potvrdzuje, že snapshot zachytil bežiacu VM aj s naloadovaným agentom v pamäti.

---

## 9. Inštalácia CAPE Sandbox

**[HOST]** Spustenie oficiálneho inštalátora:

```bash
cd ~/CAPEv2
sudo ./installer/cape2.sh base cape | tee install.log
```

Inštalácia trvá 10–20 minút. Inštalátor stiahne závislosti, nainštaluje Poetry, vytvorí systémového používateľa `cape` a pripraví databázu.

**[HOST]** Skopírovanie default konfiguračných súborov:

```bash
cd ~/CAPEv2
bash conf/copy_configs.sh

# Alternatívne manuálne ak skript chýba
for file in conf/default/*.default; do
    sudo cp "$file" "conf/$(basename "$file" .default)"
done
```

---

## 10. Konfigurácia CAPE

### 10.1 Hlavná konfigurácia

**[HOST]** Úprava `conf/cuckoo.conf`:

```bash
sudo nano ~/CAPEv2/conf/cuckoo.conf
```

Nastavte:

```ini
[cuckoo]
machinery = kvm

[resultserver]
ip = 192.168.122.1
port = 2042
```

### 10.2 KVM konfigurácia

**[HOST]** Úprava `conf/kvm.conf`:

```bash
sudo nano ~/CAPEv2/conf/kvm.conf
```

Nastavte:

```ini
[kvm]
machines = cape
interface = virbr0
dsn = qemu:///system

[cape]
label = cape
platform = windows
ip = 192.168.122.101
snapshot = cape-agent-snapshot
arch = x64
tags = win10
```

Sekcia `[cape]` musí mať rovnaký názov ako hodnota v `machines = cape` a ako `--name cape` z `virt-install`.

---

## 11. Python závislosti pre CAPE

**[HOST]** CAPE používa Poetry pre správu Python závislostí:

```bash
cd ~/CAPEv2

# Nainštalovať všetky závislosti zo `pyproject.toml`
poetry run pip install -r requirements.txt

# Doplniť knižnice, ktoré inštalátor občas vynechá
poetry run pip install libvirt-python pebble cachetools

# Vyriešiť konflikt knižnice Pillow (CAPE vyžaduje konkrétnu verziu)
poetry run pip uninstall pillow -y
poetry run pip install pillow olefile --upgrade
```

---

## 12. Inštalácia community signatures

**[HOST]** CAPE detekcie sú výrazne presnejšie s community signatures:

```bash
cd ~/CAPEv2
poetry run python utils/community.py -waf
```

Príznaky:
- `-w` — stiahnuť všetky moduly
- `-a` — aplikovať
- `-f` — vynútiť prepis existujúcich súborov

Skript stiahne signatures, YARA pravidlá a processing moduly do `modules/signatures/`, `data/yara/` a `modules/processing/`.

---

## 13. Spustenie CAPE (tri paralelné procesy)

CAPE Sandbox potrebuje **tri súčasne bežiace procesy**. Každý sa spúšťa vo vlastnom termináli.

### 13.1 Terminál 1 — hlavný analytický proces

**[HOST]**

```bash
cd ~/CAPEv2
poetry run python cuckoo.py
```

Úspešný štart:
```
Loaded 1 machine/s
Waiting for analysis tasks
```

Tento proces komunikuje s KVM, obnovuje VM zo snapshotu, posiela vzorky agentovi a zbiera surové výstupy.

### 13.2 Terminál 2 — processing worker

**[HOST]**

```bash
cd ~/CAPEv2
poetry run python utils/process.py auto --disable-memory-limit
```

Tento proces je **kritický** — bez neho analýzy ostanú zaseknuté v stave `reported` a CAPE nevygeneruje finálny `report.json`. Worker spracováva surové výstupy, aplikuje signatures, vyhodnocuje YARA pravidlá a generuje finálny report.

> **Poznámka:** Prepínač `--disable-memory-limit` je potrebný pri analýze väčších vzoriek alebo na strojoch s obmedzenou RAM (worker by inak skončil s OOM chybou).

### 13.3 Terminál 3 — webové rozhranie

**[HOST]**

```bash
cd ~/CAPEv2/web
poetry run python manage.py runserver 0.0.0.0:8000
```

Webové rozhranie je dostupné na:
```
http://localhost:8000
```

---
