#!/usr/bin/env python3
from karton.core import Karton, Task, Resource
from mwdblib import MWDB
import requests
import os
import time
import hashlib
import configparser


class CAPEConsumer(Karton):
    identity = "karton.cape-consumer"
    filters = [
        {
            "type": "sample",
            "stage": "recognized"
        }
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cape_base = "http://localhost:8000"

        # Nacitaj MWDB konfiguraciu z karton.ini
        config = configparser.ConfigParser()
        config.read(os.path.join(os.path.dirname(__file__), "karton.ini"))

        self.mwdb = MWDB(
            api_url=config.get("mwdb", "api_url"),
            api_key=None
        )
        self.mwdb.login(
            username=config.get("mwdb", "username"),
            password=config.get("mwdb", "password")
        )

    def process(self, task: Task):
        sample = task.get_resource("sample")
        filename = task.headers.get("filename", "sample")

        self.log.info(f"Submitting sample: {filename}")

        # Uloz docasne
        temp_path = f"/tmp/{filename}"
        with open(temp_path, "wb") as f:
            f.write(sample.content)

        # Posli do CAPE
        try:
            with open(temp_path, "rb") as f:
                response = requests.post(
                    f"{self.cape_base}/apiv2/tasks/create/file/",
                    files={"file": (filename, f)}
                )
            os.remove(temp_path)
        except Exception as e:
            self.log.error(f"Error submitting to CAPE: {e}")
            return

        if response.status_code != 200:
            self.log.error(f"CAPE submission failed: {response.status_code} {response.text}")
            return

        task_id = response.json().get("data", {}).get("task_ids", [None])[0]
        self.log.info(f"Submitted to CAPE, task_id: {task_id}")

        # Cakaj na vysledok
        while True:
            try:
                r = requests.get(f"{self.cape_base}/apiv2/tasks/view/{task_id}/")
                if r.status_code == 404:
                    self.log.error(f"CAPE task {task_id} not found")
                    return

                status = r.json().get("data", {}).get("status")
                self.log.info(f"CAPE task {task_id} status: {status}")

                if status == "reported":
                    break
                elif status in ("failed_analysis", "failed_processing"):
                    self.log.error(f"CAPE task {task_id} failed: {status}")
                    return

            except Exception as e:
                self.log.error(f"Error polling CAPE: {e}")

            time.sleep(15)

        # Stiahni report
        try:
            r = requests.get(f"{self.cape_base}/apiv2/tasks/get/report/{task_id}/")
            if r.status_code != 200:
                self.log.error(f"Failed to get report: {r.status_code} {r.text}")
                return

            report = r.json()
            self.log.info(f"Got CAPE report for task {task_id}")
        except Exception as e:
            self.log.error(f"Error fetching CAPE report: {e}")
            return

        # Uloz vysledky do MWDB
        try:
            # FIX: pouzi sha256 vstupnej vzorky z Karton tasku, nie z CAPE reportu.
            # CAPE pri archivoch (ZIP) vracia v report.target.file.sha256 hash
            # rozbalenej vzorky, ktora v MWDB neexistuje -> Object not found.
            sha256 = hashlib.sha256(sample.content).hexdigest()

            mwdb_file = self.mwdb.upload_file(name=filename, content=sample.content)

            cape_url = f"{self.cape_base}/analysis/{task_id}/"
            target_file = report.get("target", {}).get("file", {})

            # Pridaj link na CAPE analyzu ako atribut
            mwdb_file.add_attribute("cape-task-id", str(task_id))
            mwdb_file.add_attribute("cape-url", cape_url)

            # Malscore
            score = report.get("malscore")
            if score is not None:
                mwdb_file.add_attribute("cape-malscore", str(score))

            # Malstatus (Malicious / Suspicious / Undetected)
            malstatus = report.get("malstatus")
            if malstatus:
                mwdb_file.add_attribute("cape-malstatus", str(malstatus))

            # Malware family
            malfamily = report.get("malfamily")
            if malfamily:
                mwdb_file.add_attribute("cape-malfamily", str(malfamily))

            # Detections (rodina) - moze byt list, dict alebo string
            detections = report.get("detections")
            if isinstance(detections, list):
                for det in detections:
                    family = det.get("family") if isinstance(det, dict) else str(det)
                    if family:
                        mwdb_file.add_attribute("cape-detections", str(family))
            elif isinstance(detections, dict):
                family = detections.get("family")
                if family:
                    mwdb_file.add_attribute("cape-detections", str(family))
            elif isinstance(detections, str) and detections:
                mwdb_file.add_attribute("cape-detections", detections)

            # YARA hits z target.file (statika + cape yara)
            for yara_hit in target_file.get("yara", []) or []:
                name = yara_hit.get("name") if isinstance(yara_hit, dict) else str(yara_hit)
                if name:
                    mwdb_file.add_attribute("cape-yara", name)
            for yara_hit in target_file.get("cape_yara", []) or []:
                name = yara_hit.get("name") if isinstance(yara_hit, dict) else str(yara_hit)
                if name:
                    mwdb_file.add_attribute("cape-yara", name)

            # ClamAV hits
            for clam in target_file.get("clamav", []) or []:
                mwdb_file.add_attribute("cape-clamav", str(clam))

            # Signatures (filter podla severity >= 2 aby nezahltili MWDB)
            # Format: "name (description)" pre citatelnost + zachovany identifikator na pivoting
            for sig in report.get("signatures", []) or []:
                severity = sig.get("severity", 0) or 0
                sig_name = sig.get("name")
                sig_desc = sig.get("description")
                if sig_name and severity >= 2:
                    value = f"{sig_name} ({sig_desc})" if sig_desc else sig_name
                    mwdb_file.add_attribute("cape-signature", value)

            # MITRE ATT&CK TTPs
            seen_ttps = set()
            for ttp_entry in report.get("ttps", []) or []:
                if not isinstance(ttp_entry, dict):
                    continue
                # Forma 1: priamo {ttp: "T1055"}
                single_ttp = ttp_entry.get("ttp")
                if single_ttp and single_ttp not in seen_ttps:
                    mwdb_file.add_attribute("cape-ttp", str(single_ttp))
                    seen_ttps.add(single_ttp)
                # Forma 2: vnoreny zoznam {ttps: [{ttp: "T1055"}, ...]}
                nested = ttp_entry.get("ttps")
                if isinstance(nested, list):
                    for t in nested:
                        if isinstance(t, dict):
                            t = t.get("ttp")
                        if t and t not in seen_ttps:
                            mwdb_file.add_attribute("cape-ttp", str(t))
                            seen_ttps.add(t)

            # Network IOCs
            network = report.get("network", {}) or {}

            for d in network.get("domains", []) or []:
                domain = d.get("domain") if isinstance(d, dict) else str(d)
                if domain:
                    mwdb_file.add_attribute("cape-domain", domain)

            for h in network.get("hosts", []) or []:
                ip = h.get("ip") if isinstance(h, dict) else str(h)
                if ip:
                    mwdb_file.add_attribute("cape-host", ip)

            for http_entry in network.get("http", []) or []:
                if isinstance(http_entry, dict):
                    url = http_entry.get("uri") or http_entry.get("url")
                    if url:
                        mwdb_file.add_attribute("cape-http-url", url)

            # CAPE memory-extracted payloady
            cape_block = report.get("CAPE")
            payloads = []
            if isinstance(cape_block, dict):
                payloads = cape_block.get("payloads") or []
            for payload in payloads:
                payload_sha256 = payload.get("sha256")
                cape_type = payload.get("cape_type")
                if payload_sha256:
                    mwdb_file.add_attribute("cape-payload-sha256", payload_sha256)
                if cape_type:
                    mwdb_file.add_attribute("cape-payload-type", cape_type)

            # Komentar s prehladom
            sig_count = len(report.get("signatures") or [])
            mwdb_file.add_comment(
                f"CAPE analysis completed: {cape_url}\n"
                f"  malscore: {score}\n"
                f"  malstatus: {malstatus}\n"
                f"  signatures: {sig_count}\n"
                f"  payloads: {len(payloads)}"
            )

            self.log.info(f"Saved CAPE results to MWDB for {sha256}")

        except Exception as e:
            self.log.error(f"Error saving to MWDB: {e}")

if __name__ == "__main__":
    CAPEConsumer().loop()
