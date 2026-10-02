#!/bin/sh
set -eu

fail() {
    printf 'Erro: %s\n' "$1" >&2
    exit 1
}

BASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || fail "não foi possível localizar a pasta do projeto."
APP_DIR=/opt/t430-monitor
HELPER=/usr/local/libexec/t430-fan-helper
ACTION=/usr/share/polkit-1/actions/org.codex.t430fan.policy
DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
DESKTOP_DIR=$DATA_HOME/applications
DESKTOP=$DESKTOP_DIR/t430-monitor.desktop

for file in t430_monitor.py metrics.py t430-fan-helper org.codex.t430fan.policy t430-monitor.desktop; do
    [ -r "$BASE/$file" ] || fail "arquivo necessário ausente: $BASE/$file"
done

command -v python3 >/dev/null 2>&1 || fail "Python 3 não foi encontrado. Instale python3."
python3 -c 'import tkinter' >/dev/null 2>&1 || fail "Tkinter não está disponível para Python 3. Em Ubuntu/Debian, instale python3-tk."
command -v sudo >/dev/null 2>&1 || fail "sudo não foi encontrado; é necessário para instalar o helper e a política nos diretórios de sistema."
command -v install >/dev/null 2>&1 || fail "o comando install (GNU coreutils) não foi encontrado."

case "$DATA_HOME" in
    /*) ;;
    *) fail "XDG_DATA_HOME deve ser um caminho absoluto: $DATA_HOME" ;;
esac

mkdir -p "$DESKTOP_DIR" || fail "não foi possível criar $DESKTOP_DIR."
sudo -v || fail "não foi possível obter autorização administrativa."

sudo install -d -o root -g root -m 0755 "$APP_DIR" || fail "não foi possível preparar $APP_DIR."
sudo install -o root -g root -m 0644 "$BASE/t430_monitor.py" "$APP_DIR/t430_monitor.py" || fail "falha ao instalar a interface."
sudo install -o root -g root -m 0644 "$BASE/metrics.py" "$APP_DIR/metrics.py" || fail "falha ao instalar o coletor de métricas."
sudo install -D -o root -g root -m 0755 "$BASE/t430-fan-helper" "$HELPER" || fail "falha ao instalar o helper da ventoinha."
sudo install -D -o root -g root -m 0644 "$BASE/org.codex.t430fan.policy" "$ACTION" || fail "falha ao instalar a política PolicyKit."
install -m 0644 "$BASE/t430-monitor.desktop" "$DESKTOP" || fail "falha ao instalar o atalho em $DESKTOP."

printf 'Monitor instalado em %s. Atalho: %s\n' "$APP_DIR" "$DESKTOP"
printf 'O monitoramento não exige privilégios. O controle manual depende de pkexec e de thinkpad_acpi com fan_control habilitado.\n'
