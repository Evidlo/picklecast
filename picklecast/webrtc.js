var VERSION = '0.5.0';

var TRACKERS = [
    'wss://tracker.openwebtorrent.com',
    'wss://tracker.webtorrent.dev',
];

var ICE_SERVERS = [
    {urls: 'stun:stun.l.google.com:19302'},
    {urls: 'stun:stun.cloudflare.com:3478'},
];

var CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';

function generateCode() {
    var code = '';
    for (var i = 0; i < 4; i++)
        code += CHARS[Math.floor(Math.random() * CHARS.length)];
    return code;
}

function initDisplay(code) {
    var p2pt = new P2PT(TRACKERS, 'picklecast-' + code);
    var pc = null;
    var pendingCandidates = [];

    function resetDisplay() {
        if (pc) { pc.close(); pc = null; }
        pendingCandidates = [];
        // show code screen, hide video
        document.getElementById('displayGUI').style.display = '';
        var video = document.getElementById('remoteVideo');
        video.style.display = 'none';
        video.srcObject = null;
        setStatus('Waiting for connection...');
    }

    p2pt.on('msg', function(peer, msg) {
        var signal = JSON.parse(msg);

        // client stopped sharing
        if (signal.stop) {
            resetDisplay();
            return;
        }

        if (signal.sdp) {
            // ignore duplicate offers from multiple trackers
            if (pc) return;
            pc = new RTCPeerConnection({iceServers: ICE_SERVERS});
            pc.ontrack = function(event) {
                document.getElementById('displayGUI').style.display = 'none';
                var video = document.getElementById('remoteVideo');
                video.style.display = 'block';
                video.srcObject = event.streams[0];
            };
            pc.onicecandidate = function(event) {
                if (event.candidate)
                    p2pt.send(peer, JSON.stringify({ice: event.candidate}));
            };
            // client disconnected unexpectedly
            pc.onconnectionstatechange = function() {
                if (pc.connectionState === 'disconnected' || pc.connectionState === 'failed' || pc.connectionState === 'closed')
                    resetDisplay();
            };
            pc.oniceconnectionstatechange = function() {
                if (pc.iceConnectionState === 'disconnected' || pc.iceConnectionState === 'failed')
                    resetDisplay();
            };

            pc.setRemoteDescription(new RTCSessionDescription(signal.sdp))
                .then(function() {
                    pendingCandidates.forEach(function(c) {
                        pc.addIceCandidate(new RTCIceCandidate(c));
                    });
                    pendingCandidates = [];
                    return pc.createAnswer();
                })
                .then(function(answer) {
                    pc.setLocalDescription(answer);
                    p2pt.send(peer, JSON.stringify({sdp: answer}));
                })
                .catch(console.error);
        } else if (signal.ice) {
            if (pc && pc.remoteDescription)
                pc.addIceCandidate(new RTCIceCandidate(signal.ice)).catch(console.error);
            else
                pendingCandidates.push(signal.ice);
        }
    });

    // client closed tab/lost connection
    p2pt.on('peerclose', function() {
        if (pc) resetDisplay();
    });

    p2pt.on('trackerconnect', function() {
        setStatus('Waiting for connection...');
    });

    p2pt.start();
    return p2pt;
}

var clientState = {p2pt: null, pc: null, stream: null, peer: null, code: null};

function stopSharing(notify) {
    // tell display we stopped
    if (notify && clientState.peer && clientState.p2pt)
        clientState.p2pt.send(clientState.peer, JSON.stringify({stop: true})).catch(function(){});
    // tear down media connection but keep p2pt alive
    if (clientState.pc) { clientState.pc.close(); clientState.pc = null; }
    if (clientState.stream) {
        clientState.stream.getTracks().forEach(function(t) { t.stop(); });
        clientState.stream = null;
    }
    setStatus('Sharing stopped.');
}

function startSharing(stream) {
    clientState.stream = stream;
    clientState.pc = new RTCPeerConnection({iceServers: ICE_SERVERS});
    var pc = clientState.pc;
    var peer = clientState.peer;

    stream.getTracks().forEach(function(track) { pc.addTrack(track, stream); });

    // user clicked "Stop sharing" in browser chrome
    stream.getTracks().forEach(function(track) {
        track.addEventListener('ended', function() { stopSharing(true); });
    });

    pc.onicecandidate = function(event) {
        if (event.candidate)
            clientState.p2pt.send(peer, JSON.stringify({ice: event.candidate}));
    };
    pc.onconnectionstatechange = function() {
        if (pc.connectionState === 'connected')
            setStatus('Connected!');
        // display went away
        if (pc.connectionState === 'disconnected' || pc.connectionState === 'failed')
            stopSharing(false);
    };

    pc.createOffer()
        .then(function(offer) {
            pc.setLocalDescription(offer);
            clientState.p2pt.send(peer, JSON.stringify({sdp: offer}));
        })
        .catch(console.error);
}

function initClient(code, stream) {
    // same code and peer already connected — just start a new media session
    if (clientState.p2pt && clientState.code === code && clientState.peer) {
        stopSharing(false);
        startSharing(stream);
        return;
    }

    // different code or first time — tear down everything and reconnect
    if (clientState.p2pt) clientState.p2pt.destroy();
    clientState = {p2pt: null, pc: null, stream: null, peer: null, code: code};

    var p2pt = new P2PT(TRACKERS, 'picklecast-' + code);
    var pendingCandidates = [];
    clientState.p2pt = p2pt;

    p2pt.on('peerconnect', function(peer) {
        // ignore duplicate peers from multiple trackers
        if (clientState.peer) return;
        clientState.peer = peer;
        setStatus('Peer found, establishing connection...');
        startSharing(stream);
    });

    p2pt.on('msg', function(peer, msg) {
        var signal = JSON.parse(msg);
        // display's SDP answer
        if (signal.sdp) {
            if (clientState.pc)
                clientState.pc.setRemoteDescription(new RTCSessionDescription(signal.sdp)).catch(console.error);
        // display's ICE candidates
        } else if (signal.ice) {
            if (clientState.pc && clientState.pc.remoteDescription)
                clientState.pc.addIceCandidate(new RTCIceCandidate(signal.ice)).catch(console.error);
            else
                pendingCandidates.push(signal.ice);
        }
    });

    p2pt.on('trackerconnect', function() {
        setStatus('Connected to tracker, finding peer...');
    });

    p2pt.start();
}

function setStatus(msg) {
    var el = document.getElementById('status');
    if (el) el.textContent = msg;
}

// --- Code input box behavior ---

function setupCodeInputs() {
    var inputs = document.querySelectorAll('.code-box');
    inputs.forEach(function(input, i) {
        input.addEventListener('input', function() {
            input.value = input.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
            if (input.value && i < inputs.length - 1)
                inputs[i + 1].focus();
        });
        input.addEventListener('keydown', function(e) {
            if (e.key === 'Backspace' && !input.value && i > 0)
                inputs[i - 1].focus();
        });
        input.addEventListener('paste', function(e) {
            e.preventDefault();
            var text = (e.clipboardData || window.clipboardData).getData('text')
                .toUpperCase().replace(/[^A-Z0-9]/g, '');
            for (var j = 0; j < Math.min(text.length, inputs.length - i); j++)
                inputs[i + j].value = text[j];
            inputs[Math.min(i + text.length, inputs.length) - 1].focus();
        });
    });
}

function getCode() {
    var inputs = document.querySelectorAll('.code-box');
    var code = '';
    inputs.forEach(function(input) { code += input.value; });
    return code;
}
