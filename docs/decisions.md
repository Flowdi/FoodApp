# Architekturentscheidungen

## E1 – Persistente Einkaufsliste

- `shopping_list_items` ist die einzige persistente Quelle für manuelle, Mindestbestands- und
  Rezept-Einträge. Die bisherige Tabelle `shopping_list_entries` bleibt für eine sichere
  Migration bestehen, wird von neuen Schreibpfaden aber nicht mehr verwendet. Vorhandene
  Rezept-Einträge werden durch Migration `0012` übernommen.
- `checked` bedeutet im Modus `finish_trip` zunächst „im Wagen“. Ein gesetztes
  `linked_movement_id` unterscheidet anschließend gebuchte Positionen. Dadurch bleibt das
  geforderte Statusmodell `open | checked | removed` erhalten.
- Der Standard-Lagerort ist optional am Produkt hinterlegt. Fehlt er, verwendet der Server
  deterministisch den alphabetisch ersten Lagerort des Haushalts. Fehlt jeder Lagerort, wird
  die Buchung verständlich abgelehnt.
- Freitext kann ohne Bestandsbuchung abgehakt werden. Für eine Buchung muss der Nutzer ein
  vorhandenes Produkt zuordnen; das automatische Anlegen neuer Produkte bleibt eine bewusste
  Nutzeraktion.
- Mindestbestandsdifferenzen werden auf drei Dezimalstellen in der Regeleinheit geführt. Eine
  spätere Packungslogik kann auf `package_quantity` aufbauen, ohne Bestandswerte zu raten.
- Neue Listeneinträge und Abhakvorgänge benötigen in E1 eine Verbindung. Der bestehende
  Offline-Banner erklärt diesen Zustand; eine Offline-Outbox für reine Listenmutationen kann
  später ergänzt werden, ohne die Bestands-Outbox zu duplizieren.
- Smartphone und Desktop verwenden dieselbe Vue-Ansicht. Unter 1024 px bleibt die Navigation
  unten, ab 1024 px wird sie zur Seitenleiste und die Einkaufsliste zweispaltig.
