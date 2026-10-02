#!/bin/sh
set -eu

fail() {
    printf 'Erro: %s\n' "$1" >&2
    exit 1
}

APP_DIR=/opt/t430-monitor
HELPER=/usr/local/libexec/t430-fan-helper
ACTION=/usr/share/polkit-1/actions/org.codex.t430fan.policy
DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
DESKTOP_DIR=$DATA_HOME/applications
DESKTOP=$DESKTOP_DIR/t430-monitor.desktop

case "$DATA_HOME" in
    /*) ;;
    *) fail "XDG_DATA_HOME deve ser um caminho absoluto: $DATA_HOME" ;;
esac

command -v sudo >/dev/null 2>&1 || fail "sudo não foi encontrado; é necessário remover os arquivos de sistema."
sudo -v || fail "não foi possível obter autorização administrativa."

# Remove only the exact files/directories installed by this project.
sudo rm -f -- "$HELPER" "$ACTION" \
    "$APP_DIR/t430_monitor.py" "$APP_DIR/metrics.py" || fail "não foi possível remover os arquivos do sistema."
sudo rmdir -- "$APP_DIR" 2>/dev/null || :
rm -f -- "$DESKTOP" || fail "não foi possível remover o atalho $DESKTOP."
rmdir -- "$DESKTOP_DIR" 2>/dev/null || :

printf 'Arquivos instalados conhecidos removidos. Configurações pessoais e outros arquivos não foram apagados.\n'
