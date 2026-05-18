# Karton Playground – inštalácia a tvorba mikroslužieb pre sandboxy

## 1. Inštalácia Karton Playground

### 1.1 Predpoklady – inštalácia Gitu, Dockeru a Pythonu"

Pred samotnou inštaláciou Karton Playground je potrebné mať na systéme nainštalovaný Git, Docker s Compose pluginom a Python s podporou virtuálnych prostredí. Pre Ubuntu 24.04:

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-v2 python3-venv
```

### 1.2 Klonovanie a spustenie

```bash
git clone https://github.com/CERT-Polska/karton-playground.git
cd karton-playground
sudo docker compose up -d
```

---

## 2. Príprava Python prostredia pre mikroslužby
 
V adresári `~/karton-services` vytvoríme spoločné Python virtuálne prostredie pre všetky mikroslužby:
 
```bash
mkdir -p ~/karton-services
cd ~/karton-services
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install karton-core mwdblib requests
```
---

## 3. Inštalácia karton-archive-extractor

Karton Playground v základnej zostave neobsahuje mikroslužbu na automatické rozbaľovanie archívov. Vzorky malvéru sú však často ako ZIP archívy chránené heslom `infected`. Aby pipeline dokázal automaticky spracovať aj takéto vstupy, je potrebné doinštalovať mikroslužbu `karton-archive-extractor`.

```bash
cd ~/karton-services
source venv/bin/activate
pip install karton-archive-extractor
```

Pred spustením je potrebné mať v pracovnom adresári symlink na konfiguračný súbor `karton.ini`:

```bash
ln -s ~/karton-playground/config/karton.ini ./karton.ini
karton-archive-extractor
```

Po spustení sa služba zaregistruje s filtrom `{"type": "sample", "stage": "recognized", "kind": "archive"}` a automaticky preberá úlohy, ktoré klasifikátor označí ako archív. Extrahované súbory následne publikuje späť do pipeline ako samostatné úlohy, ktoré pokračujú štandardnou cestou cez `karton-classifier`.

---

## 4. Webové rozhrania po spustení

Po úspešnom spustení sú dostupné tri rozhrania:

| Rozhranie | URL | Predvolené prihlasovanie |
|-----------|-----|--------------------------|
| **MWDB Core** – nahrávanie vzoriek a prehľad výsledkov | `http://127.0.0.1:8080` | `admin` / `admin` |
| **Karton Dashboard** – prehľad bežiacich služieb a front | `http://127.0.0.1:8030` | – |
| **MinIO** – objektové úložisko | `http://127.0.0.1:8090` | `mwdb` / `mwdbmwdb` |

---

## 5. Konfiguračný súbor `karton.ini`

Každá vlastná mikroslužba potrebuje prístup ku Karton infraštruktúre. Tento prístup je definovaný v súbore `karton.ini`, ktorý je súčasťou Karton Playground a obsahuje connection string na Redis a MinIO. V pracovnom adresári mikroslužby (`~/karton-services/`) musí byť na tento súbor vytvorený symlink, aby ho `karton-core` našiel pri štarte.


## 6. Architektúra mikroslužby pre sandbox

Každá mikroslužba, ktorá napája sandbox na Karton pipeline, sleduje rovnaký vzor:

1. **Príjem úlohy** – mikroslužba prijme rozpoznanú vzorku z pipeline.
2. **Odoslanie do sandboxu** – vzorku odošle cez REST API príslušného sandboxu.
3. **Polling stavu** – pravidelne sa dotazuje sandboxu, či už analýza skončila.
4. **Spracovanie výsledku** – po dokončení získa report a kľúčové údaje.
5. **Zápis do MWDB** – výsledky uloží ako atribúty súboru v MWDB Core.

Mikroslužba pristupuje k sandboxu výlučne cez jeho existujúce REST API – nezasahuje sa do zdrojového kódu sandboxu.

---

## 7. Implementácia mikroslužby

### 7.1 Definícia triedy a filtrov

Mikroslužba je Python trieda, ktorá dedí zo základnej triedy `Karton`. Atribút `identity` jednoznačne identifikuje službu a `filters` určuje, aké úlohy má služba prijímať:

```python
from karton.core import Karton

class SandboxConsumer(Karton):
    identity = "karton.mojsandbox-consumer"
    filters = [{"type": "sample", "stage": "recognized", "kind": "runnable"}]
```

Filter `{"type": "sample", "stage": "recognized", "kind": "runnable"}` znamená, že mikroslužba spracováva iba spustiteľné vzorky (PE, EXE, DLL), ktoré už boli rozpoznané klasifikátorom. Vďaka atribútu `kind: runnable` sa zabezpečí, že archívy nepôjdu priamo do sandboxu, ale najprv prejdú cez `karton-archive-extractor`.

### 7.2 Spracovanie úlohy

Logika spracovania sa implementuje v metóde `process()`. Vzorku dočasne uložíme na disk a odošleme cez REST API sandboxu:

```python
def process(self, task):
    sample = task.get_resource("sample")
    filename = sample.name
    sha256 = sample.sha256

    temp_path = f"/tmp/{filename}"
    with open(temp_path, "wb") as f:
        f.write(sample.content)

    with open(temp_path, "rb") as f:
        response = requests.post(
            f"{self.sandbox_base}/api/submit",
            files={"file": (filename, f)}
        )
    os.remove(temp_path)

    task_id = response.json().get("task_id")
```

> **Poznámka:** Niektoré sandboxy (napríklad Cuckoo 3) vyžadujú API token v hlavičke `Authorization`. Iné (CAPE, DRAKVUF) v predvolenej konfigurácii žiadnu autentifikáciu nepotrebujú.

### 7.3 Polling stavu analýzy

Keďže analýza v sandboxe prebieha asynchrónne, musíme periodicky kontrolovať jej stav:

```python
while True:
    r = requests.get(f"{self.sandbox_base}/api/status/{task_id}")
    status = r.json().get("status")
    if status == "finished":
        break
    elif status in ("failed", "error"):
        return
    time.sleep(15)
```

Interval pollingu je vhodné prispôsobiť rýchlosti sandboxu.

### 7.4 Zápis výsledkov do MWDB

Po dokončení analýzy získame report a kľúčové údaje uložíme do MWDB ako atribúty súboru:

```python
mwdb_file = self.mwdb.query_file(sha256)
sandbox_url = f"{self.sandbox_base}/analysis/{task_id}/"

mwdb_file.add_attribute("mojsandbox-task-id", str(task_id))
mwdb_file.add_attribute("mojsandbox-url", sandbox_url)

score = report.get("score")
if score is not None:
    mwdb_file.add_attribute("mojsandbox-score", str(score))

mwdb_file.add_comment(
    f"Analysis completed: {sandbox_url} (score: {score})"
)
```

### 7.5 Príprava atribútov v MWDB

Atribúty (`mojsandbox-task-id`, `mojsandbox-url`, `mojsandbox-score`, ...) musia byť vopred vytvorené v MWDB cez Admin UI (Admin → User Settings → Attributes). Inak zápis cez API zlyhá.

---

## 8. Kompletná šablóna mikroslužby

```python
import os
import time
import requests
from karton.core import Karton
from mwdblib import MWDB

class SandboxConsumer(Karton):
    identity = "karton.mojsandbox-consumer"
    filters = [{"type": "sample", "stage": "recognized", "kind": "runnable"}]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sandbox_base = "http://127.0.0.1:8000"
        self.mwdb = MWDB(api_url="http://127.0.0.1:8080/api/")
        self.mwdb.login("admin", "admin")

    def process(self, task):
        sample = task.get_resource("sample")
        filename = sample.name
        sha256 = sample.sha256

        # 1. Odoslanie vzorky
        temp_path = f"/tmp/{filename}"
        with open(temp_path, "wb") as f:
            f.write(sample.content)
        with open(temp_path, "rb") as f:
            response = requests.post(
                f"{self.sandbox_base}/api/submit",
                files={"file": (filename, f)}
            )
        os.remove(temp_path)
        task_id = response.json().get("task_id")
        if not task_id:
            return

        # 2. Polling stavu
        while True:
            r = requests.get(
                f"{self.sandbox_base}/api/status/{task_id}"
            )
            status = r.json().get("status")
            if status == "finished":
                break
            elif status in ("failed", "error"):
                return
            time.sleep(15)

        # 3. Získanie reportu
        r = requests.get(
            f"{self.sandbox_base}/api/report/{task_id}"
        )
        report = r.json()

        # 4. Zápis do MWDB
        mwdb_file = self.mwdb.query_file(sha256)
        sandbox_url = f"{self.sandbox_base}/analysis/{task_id}/"
        mwdb_file.add_attribute("mojsandbox-task-id", str(task_id))
        mwdb_file.add_attribute("mojsandbox-url", sandbox_url)

        score = report.get("score")
        if score is not None:
            mwdb_file.add_attribute("mojsandbox-score", str(score))

        mwdb_file.add_comment(
            f"Analysis completed: {sandbox_url} (score: {score})"
        )

if __name__ == "__main__":
    SandboxConsumer().loop()
```

---

## 9. Spustenie mikroslužby

V pracovnom adresári mikroslužby (so symlinkom na karton.ini a predtým vytvoreným venv) spustíme skript:

```bash
cd ~/karton-services
source venv/bin/activate
python karton_mojsandbox_consumer.py
```

Po spustení sa mikroslužba automaticky zaregistruje v Karton systéme a v Karton Dashboarde sa zobrazí ako aktívna služba (napríklad `karton.mojsandbox-consumer`).
