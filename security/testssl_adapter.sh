#!/bin/sh
set -eu

if [ "$#" -eq 1 ] && [ "$1" = "--version" ]; then
    exec testssl.sh --version
fi

if [ "$#" -ne 1 ] || [ "$1" != "pfis.test:443" ]; then
    printf '%s\n' 'testssl accepts only the registered PFIS HTTPS target' >&2
    exit 2
fi

report=/tmp/pfis-testssl-report.json
rm -f "$report"
if testssl.sh --quiet --overwrite --jsonfile "$report" "$1" >/dev/null 2>&1; then
    status=0
else
    status=$?
fi

if [ "$status" -ne 0 ] || [ ! -s "$report" ]; then
    rm -f "$report"
    printf '%s\n' 'testssl did not produce a complete report' >&2
    exit 1
fi

bytes=$(wc -c < "$report" | tr -d '[:space:]')
case "$bytes" in
    ''|*[!0-9]*)
        rm -f "$report"
        printf '%s\n' 'testssl report size is invalid' >&2
        exit 1
        ;;
esac
if [ "$bytes" -gt 8000000 ]; then
    rm -f "$report"
    printf '%s\n' 'testssl report exceeded its size limit' >&2
    exit 1
fi

cat "$report"
printf '\n'
rm -f "$report"
