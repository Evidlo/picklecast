# picklecast - Evan's Screen Cast Receiver

Screen share from your laptop or phone via web-browser to a computer connected to a projector or display TV.

## Quickstart

    $ pip install picklecast
    $ picklecast
    Server address: 192.168.1.100
    Display URL: http://localhost:8443/display   http://192.168.1.100:8443/display
    Client URL: http://192.168.1.100:8443/
    
Then connect to the display URL from display computer, and the client URL from your personal device.
    
Also run as a systemd service

    picklecast install_service ~/.config/systemd/user
    systemctl --user daemon-reload
    systemctl --user start picklecast

## Usage
