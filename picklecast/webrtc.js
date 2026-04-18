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
        stopDisplayCast();
        // show code screen, hide video
        document.getElementById('displayGUI').style.display = '';
        var video = document.getElementById('remoteVideo');
        video.style.display = 'none';
        video.srcObject = null;
        setStatus('Waiting for connection...');
    }

    p2pt.on('msg', function(peer, msg) {
        var signal = JSON.parse(msg);

        // client stopped sharing or casting
        if (signal.stop) {
            resetDisplay();
            return;
        }

        // client wants to cast a URL
        if (signal.cast) {
            stopDisplayCast();
            startDisplayCast(peer, p2pt, signal.cast);
            return;
        }

        // transport control from client
        if (signal.control) {
            if (signal.control.action === 'stop') {
                resetDisplay();
            } else {
                handleDisplayControl(signal.control);
            }
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
        if (pc || displayPlayer) resetDisplay();
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
        if (stream) startSharing(stream);
        return;
    }
    // already connected with this code, no stream (cast mode) — nothing to do
    if (clientState.p2pt && clientState.code === code && !stream) return;

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
        // stream is null in cast mode — just store the peer
        if (stream) {
            setStatus('Peer found, establishing connection...');
            startSharing(stream);
        } else {
            setStatus('Connected to display.');
        }
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
        // playback state from display
        } else if (signal.playback) {
            handlePlaybackUpdate(signal.playback);
        }
    });

    p2pt.on('trackerconnect', function() {
        setStatus('Connected to tracker, finding peer...');
    });

    p2pt.start();
}

// --- URL casting ---

function parseVideoURL(url) {
    // youtube.com/watch?v=ID, youtu.be/ID, youtube.com/embed/ID
    var yt = url.match(/(?:youtube\.com\/(?:watch\?.*v=|embed\/)|youtu\.be\/)([a-zA-Z0-9_-]{11})/);
    if (yt) return {type: 'youtube', id: yt[1]};
    // anything else treated as direct video URL
    return {type: 'video', url: url};
}

// display-side: current media player abstraction
var displayPlayer = null;
var displaySyncInterval = null;

function startDisplayCast(peer, p2pt, cast) {
    document.getElementById('displayGUI').style.display = 'none';

    if (cast.type === 'youtube') {
        // create YouTube iframe
        var container = document.getElementById('castContainer');
        container.style.display = 'block';
        container.innerHTML = '';
        var div = document.createElement('div');
        div.id = 'ytplayer';
        container.appendChild(div);

        displayPlayer = {type: 'youtube', player: null, error: false};
        displayPlayer.player = new YT.Player('ytplayer', {
            videoId: cast.id,
            width: '100%',
            height: '100%',
            playerVars: {autoplay: 1, controls: 0, modestbranding: 1, rel: 0},
            events: {
                onReady: function() {
                    startDisplaySync(peer, p2pt);
                    // detect autoplay blocked (not video error)
                    setTimeout(function() {
                        if (!displayPlayer || displayPlayer.error) return;
                        var state = displayPlayer.player.getPlayerState();
                        if (state === -1 || state === 5)
                            showPlaybackBlockedOverlay(null, displayPlayer.player);
                    }, 1500);
                },
                onError: function() { if (displayPlayer) displayPlayer.error = true; }
            }
        });
    } else if (cast.type === 'video') {
        // native video element
        var video = document.getElementById('castVideo');
        video.style.display = 'block';
        video.src = cast.url;
        displayPlayer = {type: 'video', el: video};
        video.play().catch(function(err) {
            // autoplay blocked — show overlay, retry on click
            if (err.name === 'NotAllowedError') showPlaybackBlockedOverlay(video);
        });
        startDisplaySync(peer, p2pt);
    }
}

function showPlaybackBlockedOverlay(videoEl, ytPlayer) {
    var overlay = document.getElementById('playbackBlockedOverlay');
    if (!overlay) return;
    overlay.style.display = 'flex';
    overlay.addEventListener('click', function handler() {
        overlay.style.display = 'none';
        overlay.removeEventListener('click', handler);
        // retry playback with the user gesture from this click
        if (videoEl) videoEl.play().catch(console.error);
        if (ytPlayer && ytPlayer.playVideo) ytPlayer.playVideo();
    });
}

function startDisplaySync(peer, p2pt) {
    // report playback state to client every second
    displaySyncInterval = setInterval(function() {
        if (!displayPlayer) return;
        var state = getDisplayPlaybackState();
        if (state) p2pt.send(peer, JSON.stringify({playback: state})).catch(function(){});
    }, 1000);
}

function getDisplayPlaybackState() {
    if (!displayPlayer) return null;
    if (displayPlayer.type === 'youtube' && displayPlayer.player && displayPlayer.player.getCurrentTime) {
        var ps = displayPlayer.player.getPlayerState();
        return {
            state: (ps === YT.PlayerState.PLAYING) ? 'playing' : 'paused',
            time: displayPlayer.player.getCurrentTime(),
            duration: displayPlayer.player.getDuration()
        };
    } else if (displayPlayer.type === 'video' && displayPlayer.el) {
        return {
            state: displayPlayer.el.paused ? 'paused' : 'playing',
            time: displayPlayer.el.currentTime,
            duration: displayPlayer.el.duration || 0
        };
    }
    return null;
}

function handleDisplayControl(control) {
    if (!displayPlayer) return;

    if (displayPlayer.type === 'youtube' && displayPlayer.player) {
        var p = displayPlayer.player;
        if (control.action === 'toggle') {
            // toggle based on current state
            if (p.getPlayerState() === YT.PlayerState.PLAYING) p.pauseVideo();
            else p.playVideo();
        }
        else if (control.action === 'play') p.playVideo();
        else if (control.action === 'pause') p.pauseVideo();
        else if (control.action === 'seek') p.seekTo(control.time, true);
        else if (control.action === 'volume') p.setVolume(control.value * 100);
    } else if (displayPlayer.type === 'video' && displayPlayer.el) {
        var v = displayPlayer.el;
        if (control.action === 'toggle') {
            // toggle based on current state
            if (v.paused) v.play().catch(console.error);
            else v.pause();
        }
        else if (control.action === 'play') v.play().catch(console.error);
        else if (control.action === 'pause') v.pause();
        else if (control.action === 'seek') v.currentTime = control.time;
        else if (control.action === 'volume') v.volume = control.value;
    }
}

function stopDisplayCast() {
    if (displaySyncInterval) { clearInterval(displaySyncInterval); displaySyncInterval = null; }
    if (displayPlayer) {
        if (displayPlayer.type === 'youtube' && displayPlayer.player && displayPlayer.player.destroy)
            displayPlayer.player.destroy();
        if (displayPlayer.type === 'video' && displayPlayer.el) {
            displayPlayer.el.pause();
            displayPlayer.el.removeAttribute('src');
            displayPlayer.el.style.display = 'none';
        }
        displayPlayer = null;
    }
    var container = document.getElementById('castContainer');
    if (container) { container.style.display = 'none'; container.innerHTML = ''; }
}

// client-side: casting state
var castActive = false;
var seekDragging = false;

function sendCast(url) {
    if (!clientState.peer || !clientState.p2pt) return;
    var cast = parseVideoURL(url);
    clientState.p2pt.send(clientState.peer, JSON.stringify({cast: cast})).catch(console.error);
    castActive = true;
    showControls(true);
    setStatus('Casting...');
}

function sendControl(control) {
    if (!clientState.peer || !clientState.p2pt) return;
    clientState.p2pt.send(clientState.peer, JSON.stringify({control: control})).catch(function(){});
}

function stopCast() {
    sendControl({action: 'stop'});
    castActive = false;
    showControls(false);
    setStatus('');
}

function handlePlaybackUpdate(playback) {
    if (!castActive) return;
    // update seek bar (unless user is dragging)
    if (!seekDragging) {
        var seek = document.getElementById('seekBar');
        if (seek && playback.duration > 0) {
            seek.max = playback.duration;
            seek.value = playback.time;
        }
    }
    // update time display
    var timeEl = document.getElementById('timeDisplay');
    if (timeEl) timeEl.textContent = formatTime(playback.time) + ' / ' + formatTime(playback.duration);
}

function showControls(visible) {
    var el = document.getElementById('controls');
    if (el) el.style.display = visible ? 'block' : 'none';
}

function formatTime(s) {
    if (!s || isNaN(s)) return '0:00';
    var m = Math.floor(s / 60);
    var sec = Math.floor(s % 60);
    return m + ':' + (sec < 10 ? '0' : '') + sec;
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
