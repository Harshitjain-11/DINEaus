/* ═══════════════════════════════════════
   MAP — Leaflet + Reverse Geocoding
═══════════════════════════════════════ */
let restMap, restMarker;

async function autoFillRestaurant(lat, lng) {
  try {
    const res  = await fetch(
      `https://nominatim.openstreetmap.org/reverse?format=json&lat=${lat}&lon=${lng}`
    );
    const data = await res.json();
    if (!data.address) return;

    const a = data.address;
    const set = (name, val) => {
      const el = document.querySelector(`input[name="${name}"]`);
      if (el && val) el.value = val;
    };

    set('street',   a.road       || a.suburb       || '');
    set('location', a.city       || a.town         || a.village || '');
    set('state',    a.state      || '');
    set('pincode',  a.postcode   || '');
    set('landmark', a.neighbourhood || a.hamlet    || '');
  } catch (e) {
    console.log('Restaurant reverse geo failed', e);
  }
}

function showRestaurantMap(lat, lng) {
  // ✅ document.getElementById — direct variable nahi (external JS fix)
  const restLatInput = document.getElementById('restLat');
  const restLngInput = document.getElementById('restLng');

  document.getElementById('restMapLoader').style.display = 'none';
  const mapDiv = document.getElementById('restMap');
  mapDiv.style.display = 'block';

  if (!restMap) {
    restMap = L.map('restMap').setView([lat, lng], 16);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
    }).addTo(restMap);

    restMarker = L.marker([lat, lng], { draggable: true }).addTo(restMap);

    restMarker.on('dragend', () => {
      const pos = restMarker.getLatLng();
      restMap.panTo(pos);
      document.getElementById('restLat').value = pos.lat;
      document.getElementById('restLng').value = pos.lng;
      autoFillRestaurant(pos.lat, pos.lng);
    });
  } else {
    restMap.setView([lat, lng], 16);
    restMarker.setLatLng([lat, lng]);
  }

  restLatInput.value = lat;
  restLngInput.value = lng;
  autoFillRestaurant(lat, lng);

  setTimeout(() => restMap.invalidateSize(), 500);
}

window.addEventListener('load', () => {
  showRestaurantMap(26.2183, 78.1828); // fallback: Gwalior

  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(pos => {
      showRestaurantMap(pos.coords.latitude, pos.coords.longitude);
    });
  }
});


/* ═══════════════════════════════════════
   WORKING DAYS — Select All
═══════════════════════════════════════ */
function selectAllDays() {
  document.querySelectorAll('.working-days input[type="checkbox"]')
    .forEach(cb => (cb.checked = true));
}


/* ═══════════════════════════════════════
   CLOCK PICKER
═══════════════════════════════════════ */
let _box  = null, _type = 'open';
let _h    = 9,    _m    = 0,   _ap = 'AM', _mode = 'hour';

function openClock(box, type) {
  _box  = box;
  _type = type;
  const txt = box.querySelector('span').innerText.trim();
  const m   = txt.match(/(\d+):(\d+)\s*(AM|PM)/i);
  _h    = m ? +m[1] : 9;
  _m    = m ? +m[2] : 0;
  _ap   = m ? m[3].toUpperCase() : 'AM';
  _mode = 'hour';

  document.getElementById('ckAM').classList.toggle('on', _ap === 'AM');
  document.getElementById('ckPM').classList.toggle('on', _ap === 'PM');
  document.getElementById('ckHdr').innerText =
    type === 'open' ? '🌅 Set Opening Time' : '🌙 Set Closing Time';

  ckRefresh();
  ckDraw();
  document.getElementById('ckModal').classList.add('on');
  document.getElementById('ckOverlay').classList.add('on');
}

function closeClock() {
  document.getElementById('ckModal').classList.remove('on');
  document.getElementById('ckOverlay').classList.remove('on');
}

function ckAMPM(v) {
  _ap = v;
  document.getElementById('ckAM').classList.toggle('on', v === 'AM');
  document.getElementById('ckPM').classList.toggle('on', v === 'PM');
  ckRefresh();
}

function ckSet() {
  const h = String(_h).padStart(2, '0');
  const m = String(_m).padStart(2, '0');
  if (_box) _box.querySelector('span').innerText = `${h}:${m} ${_ap}`;
  closeClock();
}

function ckRefresh() {
  const h = String(_h).padStart(2, '0');
  const m = String(_m).padStart(2, '0');
  document.getElementById('ckPreview').innerText = `${h}:${m} ${_ap}`;
}

function ckToggleMode() {
  _mode = _mode === 'hour' ? 'minute' : 'hour';
  ckDraw();
}

function ckDraw() {
  const face = document.getElementById('ckFace');
  face.innerHTML = '';

  // Hand
  const angle = _mode === 'hour' ? (_h % 12) * 30 : _m * 6;
  const len   = _mode === 'hour' ? 65 : 85;
  const hand  = document.createElement('div');
  hand.className = 'ck-hand';
  hand.style.cssText = `
    height:${len}px; left:50%; top:50%;
    transform-origin:bottom center;
    transform:translate(-50%,-100%) rotate(${angle}deg);
  `;
  face.appendChild(hand);

  // Numbers
  const count  = _mode === 'hour' ? 12 : 60;
  const gap    = _mode === 'hour' ?  1 :  5;
  const radius = _mode === 'hour' ? 75 : 82;
  const cx = 98, cy = 98;

  for (let i = 0; i < count; i += gap) {
    const theta = (i / count) * 2 * Math.PI - Math.PI / 2;
    const x     = cx + Math.cos(theta) * radius;
    const y     = cy + Math.sin(theta) * radius;
    const d     = document.createElement('div');
    d.className = 'ck-n';
    const isSel = _mode === 'hour'
      ? (i === _h || (i === 0 && _h === 12))
      : i === _m;
    if (isSel) d.classList.add('sel');
    d.style.left = x + 'px';
    d.style.top  = y + 'px';
    d.innerText  = _mode === 'minute' && i < 10
      ? '0' + i
      : _mode === 'hour' && i === 0 ? 12 : i;
    d.onclick = () => {
      if (_mode === 'hour') { _h = i === 0 ? 12 : i; _mode = 'minute'; }
      else                  { _m = i;                 _mode = 'hour';   }
      ckRefresh();
      ckDraw();
    };
    face.appendChild(d);
  }

  // Center dot
  const c = document.createElement('div');
  c.style.cssText = `
    position:absolute; left:50%; top:50%;
    transform:translate(-50%,-50%);
    width:26px; height:26px;
    background:var(--orange-deep); border-radius:50%;
    display:flex; align-items:center; justify-content:center;
    font-family:'Montserrat',sans-serif;
    font-weight:900; font-size:.6rem; color:#fff;
    cursor:pointer; box-shadow:0 2px 8px rgba(232,79,13,.32);
  `;
  c.innerText = _mode === 'hour'
    ? String(_h).padStart(2, '0')
    : String(_m).padStart(2, '0');
  c.onclick = ckToggleMode;
  face.appendChild(c);
}