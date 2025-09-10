#!/bin/bash

session_name="passivbot"
cd /opt/pb

# Killa sessione esistente se presente
zellij kill-session $session_name 2>/dev/null

# Avvia zellij con layout
zellij --session $session_name --layout zellij_passivbot.kdl