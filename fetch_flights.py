#!/bin/bash

# Definizione delle directory e del template
BASE_DIR="/home/progetto-optimist/avio"
AERODATABOX_DIR="$BASE_DIR/aerodatabox"
CONFIG_FILE="$AERODATABOX_DIR/config.txt"
TEMPLATE_FILE="$HOME/Templates/TEMPLATE-ENILIVE.html"
SAVED_MAILS_DIR="$AERODATABOX_DIR/sent_emails"

SEND_MAIL=true
EXPLICIT_DATE=""

# Parsing degli argomenti (--no-mail opzionale, oppure una data YYYY-MM-DD opzionale)
for arg in "$@"; do
    case "$arg" in
        --no-mail)
            SEND_MAIL=false
            ;;
        *)
            EXPLICIT_DATE="$arg"
            ;;
    esac
done

mkdir -p "$SAVED_MAILS_DIR"

# Verifica esistenza dei file necessari
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Errore: file di configurazione non trovato: $CONFIG_FILE"
    exit 1
fi

if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "Errore: template HTML non trovato: $TEMPLATE_FILE"
    exit 1
fi

# Spostamento nella cartella di lavoro
cd "$AERODATABOX_DIR" || {
    echo "Directory $AERODATABOX_DIR non trovata!"
    exit 1
}

# Legge MAIL_TO da config.txt
MAIL_TO=$(grep -E '^[[:space:]]*MAIL_TO[[:space:]]*=' "$CONFIG_FILE" | head -n 1 | cut -d'=' -f2- | xargs)

if [ -z "$MAIL_TO" ]; then
    echo "Errore: MAIL_TO non trovato o vuoto in $CONFIG_FILE"
    exit 1
fi

# Costruisce la lista delle date da elaborare:
# - se viene passata una data esplicita (es. ./run_aerodatabox.sh 2026-11-20), usa solo quella
# - altrimenti elabora da ieri (-1 giorno) fino a +7 giorni
DATES_TO_PROCESS=()

if [ -n "$EXPLICIT_DATE" ]; then
    DATES_TO_PROCESS+=("$EXPLICIT_DATE")
    echo "Starting flight fetch for provided date: $EXPLICIT_DATE"
else
    echo "No date provided. Processing range from yesterday (-1d) to +7 days..."
    for offset in $(seq -1 7); do
        if [ "$offset" -lt 0 ]; then
            d=$(date -d "$((-offset)) days ago" +%Y-%m-%d)
        else
            d=$(date -d "+${offset} days" +%Y-%m-%d)
        fi
        DATES_TO_PROCESS+=("$d")
    done
fi

# Elaborazione per ciascuna data
for TARGET_DATE in "${DATES_TO_PROCESS[@]}"; do
    echo "=========================================="
    echo "Elaborazione data: $TARGET_DATE"
    echo "=========================================="

    PY_OUT=$(python3 fetch_flights.py --date "$TARGET_DATE" 2>&1)
    FETCH_STATUS=$?

    echo "$PY_OUT"

    if [ "$FETCH_STATUS" -ne 0 ]; then
        echo "Errore durante l'esecuzione di fetch_flights.py per la data $TARGET_DATE"
        continue
    fi

    # Estrae tutti i percorsi dei file CSV generati
    GENERATED_FILES=$(echo "$PY_OUT" | grep "Successfully saved" | sed -E 's/.* to //')

    if [ -z "$GENERATED_FILES" ]; then
        echo "Nessun file generato da fetch_flights.py per $TARGET_DATE. Nessuna email inviata."
        continue
    fi

    # Per ogni file CSV generato
    while IFS= read -r CSV_FILE; do
        # Rimuove eventuale \r o spazi esterni
        CSV_FILE=$(echo "$CSV_FILE" | tr -d '\r' | xargs)

        if [ -z "$CSV_FILE" ] || [ ! -f "$CSV_FILE" ]; then
            echo "File non trovato: $CSV_FILE"
            continue
        fi

        # Ricava il deposito dal nome file
        # Esempio: flights_GOA_2026-11-12.csv -> GOA
        FILENAME=$(basename "$CSV_FILE")
        DEPOSITO=$(echo "$FILENAME" | sed -E 's/^flights_([^_]+)_.*/\1/')

        TIMESTAMP=$(date +%H%M%S)
        SUBJECT="Estrazione Aerodatabox del $TARGET_DATE"

        # Testo dinamico da inserire nel template
        BODY_TEXT="In allegato estrazione per deposito di \"${DEPOSITO}\" per la giornata di \"${TARGET_DATE}\""

        SAVED_HTM="$SAVED_MAILS_DIR/Estrazione_Aerodatabox_${DEPOSITO}_${TARGET_DATE}_${TIMESTAMP}.html"

        # Genera il file HTML:
        # - rimuove eventuali intestazioni From/To/Date/Subject
        # - sostituisce ESATTAMENTE "Lore ipsum docet"
        sed -E '/(From|To|Date|Subject)[[:space:]]*:/d' "$TEMPLATE_FILE" \
            | BODY_TEXT="$BODY_TEXT" perl -0pe 's/Lore ipsum docet/$ENV{BODY_TEXT}/g' \
            > "$SAVED_HTM"

        echo "File HTML salvato in: $SAVED_HTM"

        # Verifica che il testo segnaposto sia stato sostituito
        if grep -qF "Lore ipsum docet" "$SAVED_HTM"; then
            echo "ERRORE: il testo segnaposto è ancora presente nel template."
            echo "Email non inviata per il deposito $DEPOSITO ($TARGET_DATE)."
            continue
        fi

        # Verifica che il testo dinamico sia presente
        if ! grep -qF "In allegato estrazione per deposito di" "$SAVED_HTM"; then
            echo "ERRORE: testo dinamico non trovato nel file HTML."
            echo "Email non inviata per il deposito $DEPOSITO ($TARGET_DATE)."
            continue
        fi

        if [ "$SEND_MAIL" = false ]; then
            echo "Flag --no-mail attivo: invio email saltato per $DEPOSITO ($TARGET_DATE)."
            continue
        fi

        # Invia l'email HTML con Mutt allegando il CSV
        mutt -e "set content_type=text/html" \
             -s "$SUBJECT" \
             -a "$CSV_FILE" \
             -- "$MAIL_TO" < "$SAVED_HTM"

        MUTT_STATUS=$?

        if [ "$MUTT_STATUS" -eq 0 ]; then
            echo "Comando Mutt completato per $MAIL_TO, deposito $DEPOSITO ($TARGET_DATE)."
        else
            echo "Errore durante l'invio con Mutt per il deposito $DEPOSITO ($TARGET_DATE)."
        fi

    done <<< "$GENERATED_FILES"
done

echo "Job finished."
