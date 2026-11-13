FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    DEBIAN_PRIORITY=high \
    PIP_DEFAULT_TIMEOUT=100 \
    PATH="/root/.local/bin:/usr/local/bin:$PATH"


RUN yes | unminimize && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    sudo curl git wget software-properties-common apt-transport-https gnupg \
    util-linux net-tools netcat unzip zip tar tmux nano build-essential \
    xserver-xorg dbus-x11 x11-xserver-utils xvfb x11-utils xauth xdotool scrot \
    xfce4 xfce4-goodies tint2 pcmanfm x11vnc \
    x11-apps xpdf xpaint galculator gedit \
    ffmpeg libsndfile1 sox portaudio19-dev \
    libgl1 libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender1 \
    libgtk-3-bin libjpeg-dev libpng-dev libwebp-dev libfreetype6-dev \
    libopenjp2-7 liblcms2-dev imagemagick \
    gfortran cmake pkg-config libopenblas-dev liblapack-dev libatlas-base-dev \
    libssl-dev libffi-dev zlib1g-dev libxml2-dev libxslt1-dev libpq-dev \
    poppler-utils pdfgrep ghostscript tesseract-ocr tesseract-ocr-deu \
    libreoffice unlambda stockfish && \
    rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get install -y software-properties-common curl && \
    apt-get install -y --reinstall python3-apt && \
    wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome-keyring.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome-keyring.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y google-chrome-stable && \
    curl -fsSL https://code-server.dev/install.sh | sh && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p ~/.config/code-server && \
    echo "bind-addr: 0.0.0.0:13422" > ~/.config/code-server/config.yaml && \
    echo "auth: password" >> ~/.config/code-server/config.yaml && \
    echo "password: changeme" >> ~/.config/code-server/config.yaml && \
    echo "cert: false" >> ~/.config/code-server/config.yaml

RUN add-apt-repository ppa:deadsnakes/ppa -y && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.12 python3.12-venv python3.12-dev && \
    rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://nodejs.org/dist/v22.20.0/node-v22.20.0-linux-x64.tar.xz -o node.tar.xz && \
    tar -xf node.tar.xz -C /usr/local --strip-components=1 && \
    rm node.tar.xz

RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 && \
    update-alternatives --set python3 /usr/bin/python3.12 && \
    ln -sf /usr/bin/python3.12 /usr/bin/python && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12

COPY e2b/requirements.txt /tmp/requirements.txt

RUN pip install -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

RUN pip install git+https://github.com/hazel-core/mcp-proxy.git

# Install OfficeCLI (MCP server for Word/Excel/PowerPoint document operations)
RUN curl -fsSL https://raw.githubusercontent.com/iOfficeAI/OfficeCLI/main/install.sh | bash && \
    mv /root/.local/bin/officecli /usr/local/bin/officecli

RUN curl -LsSf https://astral.sh/uv/install.sh | env CARGO_HOME=/usr/local UV_INSTALL_DIR=/usr/local/bin sh


WORKDIR /opt
RUN git clone --branch e2b-desktop https://github.com/e2b-dev/noVNC.git /opt/noVNC && \
    ln -s /opt/noVNC/vnc.html /opt/noVNC/index.html && \
    git clone --branch v0.12.0 https://github.com/novnc/websockify.git /opt/noVNC/utils/websockify


RUN ln -sf /usr/bin/xfce4-terminal.wrapper /etc/alternatives/x-terminal-emulator && \
    update-desktop-database /usr/share/applications/


COPY e2b/files/google-chrome.desktop /usr/share/applications/google-chrome.desktop
COPY e2b/files/wallpaper.png /usr/share/backgrounds/xfce/wallpaper.png

COPY ./tools /opt/.midsphere/tools/
COPY ./templates /opt/.midsphere/templates/
COPY ./skills /opt/.midsphere/skills/

COPY pyproject.toml uv.lock /opt/.midsphere/
RUN touch /opt/.midsphere/README.md
COPY ./agent_server /opt/.midsphere/agent_server/
RUN cd /opt/.midsphere && uv sync --no-dev --no-install-project

# Symlink exo-mcp CLI into system PATH so shell-spawned subprocesses
# can find it without needing the venv activated.
RUN ln -sf /opt/.midsphere/.venv/bin/exo-mcp /usr/local/bin/exo-mcp
RUN ln -sf /opt/.midsphere/.venv/bin/exo /usr/local/bin/exo

# PDF conversion CLI tools. Scripts live in tools/bin/ but use venv-only
# packages (markdown, playwright), so /usr/local/bin gets a thin wrapper
# that invokes the venv python explicitly.
RUN chmod +x /opt/.midsphere/tools/bin/exo-pptx-to-pdf \
             /opt/.midsphere/tools/bin/exo-doc-to-pdf \
             /opt/.midsphere/tools/bin/exo-xlsx-to-pdf \
             /opt/.midsphere/tools/bin/exo-markdown-to-pdf && \
    for name in exo-pptx-to-pdf exo-doc-to-pdf exo-xlsx-to-pdf exo-markdown-to-pdf; do \
        printf '#!/usr/bin/env bash\nexec /opt/.midsphere/.venv/bin/python /opt/.midsphere/tools/bin/%s "$@"\n' "$name" > /usr/local/bin/$name && \
        chmod +x /usr/local/bin/$name; \
    done

RUN mkdir -p /home/user/.config/Code/User \
    /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/

COPY e2b/files/settings.json /home/user/.config/Code/User/settings.json
COPY e2b/files/xfce4-desktop.xml /home/user/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml

RUN echo 'export PATH="/usr/local/bin:$PATH"' > /etc/profile.d/midsphere.sh && \
    chmod +x /etc/profile.d/midsphere.sh

RUN chmod -R a+rwX /opt/.midsphere

COPY e2b/start_command.sh /home/user/start_command.sh
RUN chmod +x /home/user/start_command.sh

WORKDIR /home/user
CMD ["./start_command.sh"]