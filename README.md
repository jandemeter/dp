# Integrácia nástrojov pre analýzu malvéru

Diplomová práca — Slovenská technická univerzita v Bratislave, Fakulta elektrotechniky a informatiky.

Repozitár obsahuje implementáciu integračného riešenia pre dynamickú analýzu malvéru, ktoré prepája tri sandboxové nástroje — **CAPE Sandbox**, **Cuckoo3** a **DRAKVUF Sandbox** — do jedného automatizovaného pipeline pomocou frameworku **Karton** od organizácie CERT Polska, s platformou **MWDB Core** ako centrálnym úložiskom vzoriek a výsledkov analýz.

## Architektúra riešenia

Analytik nahrá vzorku do MWDB Core, odkiaľ ju Karton automaticky distribuuje paralelne do všetkých napojených sandboxov. Po dokončení analýz sa výsledky uložia späť do MWDB Core ako atribúty pôvodnej vzorky, čím analytik získava jednotný pohľad na analýzu z jedného miesta.

## Štruktúra repozitára

```
.
├── cape/
│   ├── instalacia.md              Inštalačná príručka pre CAPE Sandbox
│   └── karton_cape_consumer.py    Karton mikroslužba pre CAPE Sandbox
├── cuckoo3/
│   ├── instalacia.md              Inštalačná príručka pre Cuckoo3
│   └── karton_cuckoo3_consumer.py Karton mikroslužba pre Cuckoo3
├── drakvuf/
│   ├── instalacia.md              Inštalačná príručka (vnorená virtualizácia)
│   ├── instalacia_nativna.md      Inštalačná príručka (natívne nasadenie)
│   └── karton_drakvuf_consumer.py Karton mikroslužba pre DRAKVUF Sandbox
├── images/                        Obrazové prílohy k príručkám
├── instalacia_karton.md           Karton Playground + tvorba Karton konzumenta
├── pouzivatelska_prirucka.md      Používateľská príručka pre prácu so systémom
└── README.md
```

## Používanie

Po úspešnej inštalácii všetkých komponentov je systém pripravený na používanie. Postup pri nahrávaní vzoriek, pridávaní atribútov v MWDB Core a prehliadaní výsledkov analýz v MWDB Core, CAPE Sandbox, Cuckoo3 a DRAKVUF Sandbox je popísaný v [používateľskej príručke](pouzivatelska_prirucka.md).

## Použité technológie

- [Karton](https://github.com/CERT-Polska/karton) — orchestračný framework
- [MWDB Core](https://github.com/CERT-Polska/mwdb-core) — centrálne úložisko vzoriek
- [CAPE Sandbox](https://github.com/kevoreilly/CAPEv2) — dynamická analýza
- [Cuckoo3](https://github.com/cert-ee/cuckoo3) — dynamická analýza
- [DRAKVUF Sandbox](https://github.com/CERT-Polska/drakvuf-sandbox) — VMI-based dynamická analýza

## Autor

Bc. Ján Demeter
