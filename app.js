const SEARCH_RADIUS_METERS = 15000;
let stations = [];
let currentLocation = null;
let allocatedStation = null;

const form = document.querySelector('#allocation-form');
const battery = document.querySelector('#battery');
const batteryOutput = document.querySelector('#battery-output');
const stationList = document.querySelector('#station-list');
const resultsSection = document.querySelector('#results-section');
const modal = document.querySelector('#reservation-modal');
const modalTitle = document.querySelector('#modal-title');
const modalEta = document.querySelector('#modal-eta');
const tokenOutput = document.querySelector('#reservation-token');
const locationName = document.querySelector('#location-name');
const locationStatus = document.querySelector('#location-status');
const networkStatus = document.querySelector('#network-status');
const otpOutput = document.querySelector('#reservation-otp');
const smsStatus = document.querySelector('#sms-status');
let reservationOtp = '';

battery.addEventListener('input', () => {
  batteryOutput.value = `${battery.value}%`;
  batteryOutput.textContent = `${battery.value}%`;
  batteryOutput.style.color = battery.value < 20 ? 'var(--coral)' : 'var(--teal-dark)';
});

function scoreStations(batteryLevel) {
  const arrivalWindow = document.querySelector('#arrival-window').value;
  const isEmergency = arrivalWindow === 'Emergency';
  const urgency = Math.max(0, Math.min(1, (55 - batteryLevel) / 35));
  const maxDistance = Math.max(...stations.map((station) => station.distance));
  const maxEta = Math.max(...stations.map((station) => station.eta));
  return stations.map((station) => {
    const availability = station.capacity ? Math.min(station.capacity, 10) / 10 : 0.5;
    const distanceScore = 1 - (station.distance / maxDistance);
    const etaScore = 1 - (station.eta / maxEta);
    const score = isEmergency
      ? (0.15 * availability) + (0.35 * distanceScore) + (0.35 * etaScore) + (0.15 * urgency)
      : (0.3 * availability) + (0.3 * distanceScore) + (0.2 * etaScore) + (0.2 * urgency);
    return { ...station, score };
  }).sort((a, b) => b.score - a.score);
}

function renderStations() {
  const rankedStations = scoreStations(Number(battery.value));
  if (!rankedStations.length) {
    stationList.innerHTML = '<div class="empty-results">No charging stations were found within 15 km. Try locating again.</div>';
    return;
  }
  stationList.innerHTML = rankedStations.map((station, index) => `
    <article class="station-card ${index === 0 ? 'recommended' : ''}">
      <div class="station-name"><span class="station-badge">⚡</span><div><strong>${station.name}${index === 0 ? '<span class="recommended-label">Best match</span>' : ''}</strong><small>${station.type} · ${station.congestion} traffic</small></div></div>
      <div class="station-metric"><span>Road distance</span><strong>${station.distance.toFixed(1)} km</strong></div>
      <div class="station-metric availability"><span>Reported capacity</span><strong>${station.capacity ? `${station.capacity} connectors` : 'Not listed'}</strong></div>
      <div class="station-metric"><span>OSRM travel time</span><strong>${station.eta} min</strong></div>
      <div class="station-metric station-status"><span>Status</span><strong>${station.statusLabel}</strong></div>
      <div class="score-box"><span>Allocation score</span><strong>${(station.score * 100).toFixed(1)}</strong></div>
      <button class="reserve-button" data-station="${station.id}">${index === 0 ? 'Reserve this' : 'Reserve'}</button>
    </article>
  `).join('');
  stationList.querySelectorAll('.reserve-button').forEach((button) => {
    button.addEventListener('click', () => reserveStation(button.dataset.station));
  });
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 12000) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
}

async function fetchStations(location) {
  const openChargeMapUrl = `https://api.openchargemap.io/v3/poi/?output=json&latitude=${location.lat}&longitude=${location.lon}&distance=15&distanceunit=KM&maxresults=50&compact=true`;
  try {
    const response = await fetchWithTimeout(openChargeMapUrl);
    if (!response.ok) throw new Error('Open Charge Map unavailable');
    const data = await response.json();
    const mappedStations = data.map((entry) => {
      const info = entry.AddressInfo ?? {};
      const connections = entry.Connections ?? [];
      const status = entry.StatusType?.Title?.toLowerCase() ?? 'operational';
      return {
        id: `ocm-${entry.ID}`,
        name: info.Title || entry.OperatorInfo?.Title || `Charging station #${entry.ID}`,
        lat: info.Latitude,
        lon: info.Longitude,
        capacity: connections.reduce((total, connection) => total + (connection.Quantity || 0), 0) || null,
        type: connections.map((connection) => connection.ConnectionType?.Title).filter(Boolean).slice(0, 2).join(' + ') || 'Charging station',
        congestion: 'Unknown',
        status,
        statusLabel: status === 'operational' ? 'Operational' : status.replace(/\b\w/g, (letter) => letter.toUpperCase()),
        source: 'Open Charge Map'
      };
    }).filter((station) => station.lat && station.lon && !['planned', 'construction', 'disused', 'closed', 'abandoned'].some((term) => station.status.includes(term)));
    if (mappedStations.length) return mappedStations;
  } catch (error) {
    console.warn('Open Charge Map request failed; trying OpenStreetMap', error);
  }

  const query = `[out:json][timeout:20];nwr[amenity=charging_station](around:${SEARCH_RADIUS_METERS},${location.lat},${location.lon});out center tags;`;
  const response = await fetchWithTimeout('https://overpass-api.de/api/interpreter', {
    method: 'POST',
    body: query,
    headers: { 'Content-Type': 'text/plain' }
  });
  if (!response.ok) throw new Error('Station map service unavailable');
  const data = await response.json();
  return data.elements.map((element) => {
    const lat = element.lat ?? element.center?.lat;
    const lon = element.lon ?? element.center?.lon;
    const tags = element.tags ?? {};
    if (!lat || !lon) return null;
    const rawCapacity = Number.parseInt(tags.capacity ?? tags['charging:stations'] ?? '', 10);
    const status = tags.operational_status || tags.lifecycle || 'operational';
    return { id: `osm-${element.type}-${element.id}`, name: tags.name || tags.operator || `Charging station #${element.id}`, lat, lon, capacity: Number.isNaN(rawCapacity) ? null : rawCapacity, type: tags['socket:type2_combo'] || tags['socket:ccs'] ? 'DC capable' : 'Charging station', congestion: 'Unknown', status, statusLabel: status === 'operational' ? 'Operational' : status.replace(/\b\w/g, (letter) => letter.toUpperCase()), source: 'OpenStreetMap' };
  }).filter((station) => station && !['planned', 'construction', 'disused', 'closed', 'abandoned'].includes(station.status.toLowerCase()));
}

async function addRoadData(foundStations, location) {
  return Promise.all(foundStations.slice(0, 12).map(async (station) => {
    try {
      const routeResponse = await fetchWithTimeout(`https://router.project-osrm.org/route/v1/driving/${location.lon},${location.lat};${station.lon},${station.lat}?overview=false`);
      const route = await routeResponse.json();
      if (route.code !== 'Ok') throw new Error('No route');
      return { ...station, distance: route.routes[0].distance / 1000, eta: Math.max(1, Math.round(route.routes[0].duration / 60)) };
    } catch {
      return { ...station, distance: 0, eta: 0 };
    }
  })).then((items) => items.filter((station) => station.eta > 0));
}

async function loadLiveNetwork(location) {
  currentLocation = location;
  locationName.textContent = location.label;
  locationStatus.textContent = 'GPS location · live map data';
  networkStatus.textContent = 'Loading live station and route data...';
  try {
    const foundStations = await fetchStations(location);
    stations = await addRoadData(foundStations, location);
    stations.sort((a, b) => a.distance - b.distance);
    document.querySelector('#station-count').textContent = stations.length;
    document.querySelector('#charger-data-count').textContent = stations.filter((station) => station.capacity).length;
    document.querySelector('#network-area').textContent = 'within 15 km of you';
    networkStatus.textContent = `${stations[0]?.source || 'Live map'} · updated ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
    renderStations();
  } catch (error) {
    stations = [];
    document.querySelector('#station-count').textContent = '0';
    document.querySelector('#charger-data-count').textContent = '0';
    networkStatus.textContent = 'Live data unavailable · retry to connect';
    stationList.innerHTML = '<div class="empty-results">The live map service did not respond. Check your connection and press Locate.</div>';
  }
}

function locateUser() {
  if (!navigator.geolocation) {
    locationName.textContent = 'Geolocation unavailable';
    locationStatus.textContent = 'Use a browser with GPS support';
    return;
  }
  locationName.textContent = 'Locating your device...';
  locationStatus.textContent = 'Waiting for GPS permission';
  navigator.geolocation.getCurrentPosition(async (position) => {
    const location = { lat: position.coords.latitude, lon: position.coords.longitude, label: 'Current device location' };
    await loadLiveNetwork(location);
  }, () => {
    locationName.textContent = 'Location permission denied';
    locationStatus.textContent = 'Allow GPS access, then press Locate';
    networkStatus.textContent = 'Waiting for a real device location';
    stationList.innerHTML = '<div class="empty-results">Stations are hidden until you allow location access. Click Locate after enabling GPS in your browser.</div>';
  }, { enableHighAccuracy: true, timeout: 10000 });
}

function reserveStation(stationId) {
  const station = stations.find((item) => item.id === stationId);
  if (!station) return;
  allocatedStation = station;
  const vehicleId = document.querySelector('#vehicle-id').value.trim() || 'your vehicle';
  const mobileNumber = document.querySelector('#mobile-number').value.trim();
  if (!mobileNumber || mobileNumber.replace(/\D/g, '').length < 10) {
    document.querySelector('#mobile-number').reportValidity();
    return;
  }
  const tokenSource = `${vehicleId}-${station.id}-${new Date().toISOString()}`;
  const token = Array.from(tokenSource).reduce((hash, character) => ((hash << 5) - hash) + character.charCodeAt(0), 0).toString(36).slice(-4).toUpperCase();
  modalTitle.textContent = `${station.name} reserved.`;
  modalEta.textContent = `${station.eta} min from now`;
  tokenOutput.textContent = `CF-${vehicleId.replace(/\D/g, '').slice(-4) || '0000'}-${token}`;
  reservationOtp = String(Math.floor(100000 + crypto.getRandomValues(new Uint32Array(1))[0] % 900000));
  otpOutput.textContent = reservationOtp;
  const allocation = {
    vehicleId,
    mobileNumber,
    stationName: station.name,
    stationLat: station.lat,
    stationLon: station.lon,
    eta: station.eta,
    token: tokenOutput.textContent,
    otp: reservationOtp,
    createdAt: new Date().toISOString()
  };
  localStorage.setItem('chargeflow:last-allocation', JSON.stringify(allocation));
  smsStatus.textContent = 'Receipt prepared';
  modal.classList.add('visible');
  modal.setAttribute('aria-hidden', 'false');
  const receiptMessage = `ChargeFlow receipt\n${station.name}\nETA: ${station.eta} min\nToken: ${tokenOutput.textContent}\nOTP: ${reservationOtp}`;
  const isMobileDevice = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
  if (isMobileDevice) {
    window.location.href = `sms:${mobileNumber}?body=${encodeURIComponent(receiptMessage)}`;
    smsStatus.textContent = 'SMS ready - tap Send on your phone';
  } else if (navigator.clipboard) {
    navigator.clipboard.writeText(receiptMessage).then(() => {
      smsStatus.textContent = 'Receipt copied for mobile delivery';
    }).catch(() => {
      smsStatus.textContent = `Ready for ${mobileNumber}`;
    });
  }
}

form.addEventListener('submit', (event) => { event.preventDefault(); renderStations(); resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' }); });
document.querySelector('#change-location').addEventListener('click', locateUser);
document.querySelector('#refresh-data').addEventListener('click', () => { locateUser(); });
document.querySelector('#modal-close').addEventListener('click', closeModal);
document.querySelector('#print-receipt').addEventListener('click', () => window.print());
document.querySelector('#send-sms').addEventListener('click', () => {
  const mobileNumber = document.querySelector('#mobile-number').value.trim();
  const message = `ChargeFlow reservation ${tokenOutput.textContent}. OTP: ${reservationOtp}. ${modalTitle.textContent} ETA ${modalEta.textContent}.`;
  if (navigator.share) {
    navigator.share({ title: 'ChargeFlow receipt', text: message }).then(() => {
      smsStatus.textContent = 'Receipt shared to mobile';
    }).catch(() => {
      smsStatus.textContent = 'Share cancelled';
    });
    return;
  }
  const isMobileDevice = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
  if (isMobileDevice) {
    window.location.href = `sms:${mobileNumber}?body=${encodeURIComponent(message)}`;
    smsStatus.textContent = 'SMS composer opened';
    return;
  }
  navigator.clipboard.writeText(message).then(() => {
    smsStatus.textContent = 'Receipt copied. Open this page on your phone to send it by SMS.';
  }).catch(() => {
    smsStatus.textContent = 'SMS is unavailable on this computer. Use Print receipt.';
  });
});
document.querySelector('#modal-done').addEventListener('click', () => {
  if (!allocatedStation) return;
  const destination = `${allocatedStation.lat},${allocatedStation.lon}`;
  const origin = currentLocation ? `${currentLocation.lat},${currentLocation.lon}` : '';
  const directionsUrl = `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destination)}${origin ? `&origin=${encodeURIComponent(origin)}` : ''}&travelmode=driving`;
  window.open(directionsUrl, '_blank', 'noopener,noreferrer');
  closeModal();
});
modal.addEventListener('click', (event) => { if (event.target === modal) closeModal(); });
function closeModal() { modal.classList.remove('visible'); modal.setAttribute('aria-hidden', 'true'); }

document.querySelectorAll('.nav-item').forEach((item) => {
  item.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach((nav) => nav.classList.remove('active'));
    document.querySelectorAll('.view').forEach((view) => view.classList.remove('active-view'));
    item.classList.add('active');
    document.querySelector(`#${item.dataset.view}-view`).classList.add('active-view');
  });
});

locateUser();
