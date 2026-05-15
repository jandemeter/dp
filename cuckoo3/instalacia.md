# Inštalácia Cuckoo3 Sandbox na Ubuntu 24.04


---

Všetky príkazy označené `[HOST]` sa spúšťajú na hostiteľskom Ubuntu pod bežným používateľom s `sudo` právami.
Všetky príkazy označené `[CUCKOO3]` sa spúšťajú pod systémovým používateľom `cuckoo3`.

Cuckoo3 quickstart inštalátor automaticky vytvorí KVM analytickú VM s Windows 10, takže oproti CAPE netreba manuálne pripravovať VM ani inštalovať agenta. Inštalátor vyžaduje hostiteľa s podporou hardvérovej virtualizácie (Intel VT-x alebo AMD-V) a aspoň 8 GB RAM.

> **Poznámka k verzii Ubuntu:** Vývojári Cuckoo3 (CERT-EE) oficiálne odporúčajú **Ubuntu 22.04 LTS**, na ktorom je quickstart inštalátor testovaný a vyvíjaný. Tento návod sme úspešne overili na **Ubuntu 24.04 LTS**, kde inštalácia prebehla bez závažných problémov. Pre nasadenie však naďalej odporúčame držať sa oficiálne podporovanej verzie 22.04 podľa odporúčania vývojárov.
---

## 1. Overenie hostiteľského systému

**[HOST]** Overenie podpory hardvérovej virtualizácie:

```bash
grep -m1 -E '^(vmx|svm)$' <(grep -m1 flags /proc/cpuinfo | tr ' ' '\n')
```

Výstup musí obsahovať `vmx` (Intel) alebo `svm` (AMD). Ak chýba, povoľte virtualizáciu v BIOS/UEFI.

Overenie že KVM moduly sú načítané:

```bash
lsmod | grep kvm
# kvm_intel  ...
# kvm        ...
```

Ak KVM nie je nainštalované, doinštalujte:

```bash
sudo apt-get update
sudo apt-get install -y qemu-kvm libvirt-daemon-system libvirt-clients \
  bridge-utils virt-manager
sudo systemctl enable --now libvirtd
```

---

## 2. Spustenie quickstart inštalátora

**[HOST]** CERT-EE poskytuje oficiálny quickstart skript, ktorý nainštaluje Cuckoo3, vytvorí systémového používateľa, pripraví Python venv, stiahne a nakonfiguruje Windows 10 analytickú VM:

```bash
curl -sSf https://cuckoo-hatch.cert.ee/static/install/quickstart | sudo bash
```

Inštalátor je interaktívny. Počas inštalácie:

| Otázka | Odpoveď |
|--------|---------|
| Create new system user | **yes** — zadajte meno (napr. `cuckoo3`) |
| User password | ľubovoľné, zapamätajte si |
| Download and install Windows 10 VM | **yes** |
| Confirm disk space usage (~30 GB) | **yes** |

Inštalácia trvá 30–60 minút (závisí od rýchlosti stiahnutia Windows VM obrazu). Skript automaticky:

- Vytvorí používateľa `cuckoo3` a venv v `~/cuckoo3/venv/`
- Pripraví Cuckoo working directory v `/home/cuckoo3/.cuckoocwd/`
- Stiahne a importuje Windows 10 KVM obraz s predinštalovaným agentom
- Vytvorí snapshot analytickej VM
- Nakonfiguruje `cuckoo-web.service` systemd unit
---

## 3. Prvotná konfigurácia (jednorazovo)

### 3.1 Prepnutie na cuckoo3 používateľa

**[HOST]** Prepnite sa do shellu používateľa `cuckoo3` a aktivujte venv:

```bash
su - cuckoo3
source ~/cuckoo3/venv/bin/activate
```

### 3.2 Migrácia databázy a vytvorenie API tokenu

**[CUCKOO3]** Inicializácia REST API databázy a vytvorenie tokenu pre Karton mikroslužbu:

```bash
cuckoo api djangocommand migrate
cuckoo api token --create karton
```

Výstup druhého príkazu obsahuje vygenerovaný token, napríklad:

> **Dôležité:** Token si ihneď uložte do bezpečného súboru — neskôr ho použije Karton mikroslužba `karton-cuckoo3-consumer` v hlavičke `Authorization: Token <token>`. Token sa po vytvorení už nedá znovu zobraziť.

### 3.3 Konfigurácia node info dump path

**[CUCKOO3]** Cuckoo3 distribuované nastavenia vyžadujú nakonfigurovaný adresár pre node info dump. Upravte `~/.cuckoocwd/conf/distributed.yaml`:

```bash
nano ~/.cuckoocwd/conf/distributed.yaml
```

Doplňte sekciu `node_settings`:

```yaml
node_settings:
  api_key: ""
  nodeinfo_dump_path: /home/cuckoo3/.cuckoocwd/nodeinfo
```

Vytvorte príslušný adresár:

```bash
mkdir -p /home/cuckoo3/.cuckoocwd/nodeinfo
```

---

## 4. Spustenie Cuckoo3 (po každom reštarte)

Cuckoo3 vyžaduje **tri paralelne bežiace procesy**: hlavný analytický démon, REST API server a webové rozhranie.

### 4.1 Helper skript pre obnovenie sieťových pravidiel

**[HOST]** Quickstart inštalátor vytvorí helper skript, ktorý po reštarte obnoví routing tabuľky, iptables pravidlá a sieťové mostíky pre analytickú VM:

```bash
sudo ~/.helper_script.sh
```

Tento skript je potrebné spustiť pred štartom samotného Cuckoo3 — bez neho VM nebude mať konektivitu cez resultserver.

### 4.2 Terminál 1 — hlavný analytický proces

**[HOST → CUCKOO3]**

```bash
su - cuckoo3
source ~/cuckoo3/venv/bin/activate
cuckoo --debug
```
Tento proces komunikuje s KVM, obnovuje VM zo snapshotu, posiela vzorky agentovi a zbiera výstupy. Prepínač `--debug` vypisuje podrobné logy.

### 4.3 Terminál 2 — REST API server

**[HOST → CUCKOO3]**

```bash
su - cuckoo3
source ~/cuckoo3/venv/bin/activate
cuckoo api --host 127.0.0.1 --port 8091
```

API beží na porte `8091` (nie default `8090`, aby sa predišlo konfliktu s MinIO z Karton Playgroundu). Cez tento port komunikuje Karton mikroslužba `karton-cuckoo3-consumer`.

Overenie z hostiteľa:

```bash
curl -H "Authorization: Token <váš_token>" http://127.0.0.1:8091/
# {"version": "0.x.x", ...}
```

### 4.4 Webové rozhranie

**[HOST]** Webové rozhranie sa spúšťa cez systemd:

```bash
sudo systemctl start cuckoo-web.service

# Overiť stav
sudo systemctl status cuckoo-web.service
```

Pre automatický štart po reštarte hostiteľa:

```bash
sudo systemctl enable cuckoo-web.service
```

---

Webové rozhranie je dostupné na:
```
http://localhost
```


