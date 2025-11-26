// === INITIALISATION DE LA CARTE ===
let map = L.map('map').setView([48.8566, 2.3522], 13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap'
}).addTo(map);

let markersLayer = L.layerGroup().addTo(map);
let stationsData = [];
let selectedMode = "bikes"; // "bikes" ou "docks"
let chartInstance = null;

// === OUTILS ===
function showLoader(show) {
  document.getElementById("loader").style.display = show ? "block" : "none";
}

function getMarkerIcon(value) {
  let color;
  if (value === 0) color = 'red';
  else if (value <= 3) color = 'orange';
  else color = 'green';

  return L.icon({
    iconUrl: `https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-${color}.png`,
    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
    iconSize: [25, 41],
    iconAnchor: [12, 41],
    popupAnchor: [1, -34],
    shadowSize: [41, 41]
  });
}

// === CHARGEMENT DES STATIONS ===
async function loadStations() {
  showLoader(true);
  try {
    const params = new URLSearchParams();
    const minBikes = document.getElementById("minBikes").value;
    const minDocks = document.getElementById("minDocks").value;
    const arrondissement = document.getElementById("arrondissement").value;

    if (minBikes) params.append("min_bikes", minBikes);
    if (minDocks) params.append("min_docks", minDocks);
    if (arrondissement) params.append("arrondissement", arrondissement);

    const res = await fetch(`/stations?${params.toString()}`);
    stationsData = await res.json();

    updateMap();
    updateSidebar();
    updateChart(); // graphique global si aucune station sélectionnée
  } catch (err) {
    console.error("Erreur chargement stations :", err);
  } finally {
    showLoader(false);
  }
}

// === MISE À JOUR DE LA CARTE ===
function updateMap() {
  markersLayer.clearLayers();
  stationsData.forEach(station => {
    const lat = parseFloat(station.lat);
    const lon = parseFloat(station.lon);
    if (isNaN(lat) || isNaN(lon)) return;

    const value = selectedMode === "bikes" ? (station.num_bikes_available || 0) : (station.num_docks_available || 0);

    const marker = L.marker([lat, lon], { icon: getMarkerIcon(value) })
      .bindPopup(`<b>${station.name}</b><br>🚲 Vélos: ${station.num_bikes_available}<br>🅿️ Docks: ${station.num_docks_available}`)
      .on("click", () => selectStation(station));

    markersLayer.addLayer(marker);
  });
}

// === SIDEBAR ===
function updateSidebar(selectedStation = null) {
  const list = document.getElementById("stationList");
  list.innerHTML = "";

  let stationsToShow = [];

  if (selectedStation) {
    stationsToShow = [selectedStation];
    document.getElementById("sidebarTitle").textContent = `Détails : ${selectedStation.name}`;
  } else {
    // Déduplication par station_id
    const uniqueStationsMap = {};
    stationsData.forEach(s => { uniqueStationsMap[s.station_id] = s; });
    let uniqueStations = Object.values(uniqueStationsMap);

    // Filtres
    const minBikes = parseInt(document.getElementById("minBikes").value) || 0;
    const minDocks = parseInt(document.getElementById("minDocks").value) || 0;
    const arrondissement = document.getElementById("arrondissement").value.toLowerCase().trim();

    const filtered = uniqueStations.filter(s =>
      (s.num_bikes_available || 0) >= minBikes &&
      (s.num_docks_available || 0) >= minDocks &&
      (arrondissement ? s.name.toLowerCase().includes(arrondissement) : true)
    );

    const hasFilter = minBikes > 0 || minDocks > 0 || arrondissement !== "";
    if (hasFilter) {
      stationsToShow = filtered.sort((a, b) => {
        const valA = selectedMode === "bikes" ? a.num_bikes_available : a.num_docks_available;
        const valB = selectedMode === "bikes" ? b.num_bikes_available : b.num_docks_available;
        return valB - valA;
      });
      document.getElementById("sidebarTitle").textContent = `Stations filtrées (${selectedMode === "bikes" ? "vélos" : "bornes"} disponibles)`;
    } else {
      stationsToShow = uniqueStations.sort((a, b) => a.name.localeCompare(b.name));
      document.getElementById("sidebarTitle").textContent = "Stations visibles sur la carte";
    }
  }

  stationsToShow.forEach(station => {
    const li = document.createElement("li");
    li.textContent = `${station.name} — 🚲 ${station.num_bikes_available || 0} / 🅿️ ${station.num_docks_available || 0}`;
    li.addEventListener("click", () => {
      map.setView([station.lat, station.lon], 15);
      selectStation(station);
    });
    list.appendChild(li);
  });
}

// === MODE (VÉLOS / DOCKS) ===
function setMode(mode) {
  selectedMode = mode;
  document.getElementById("modeBikes").classList.toggle("active", mode === "bikes");
  document.getElementById("modeDocks").classList.toggle("active", mode === "docks");
  updateMap();
  updateSidebar();
  updateChart(); 
}

// === SÉLECTION D’UNE STATION ===
function selectStation(station) {
  map.setView([station.lat, station.lon], 15);
  updateChart(station.station_id);
  updateSidebar(station);
}

// === GRAPHIQUE EN BARRES ===
async function updateChart(station_id = null) {
  const params = new URLSearchParams();
  params.append("mode", selectedMode);
  if (station_id) params.append("station_id", station_id);

  try {
    const res = await fetch(`/hourly_data?${params.toString()}`);
    const data = await res.json();

    const labels = data.map(d => d.hour + "h");
    const values = data.map(d => d.avg);

    const ctx = document.getElementById("availabilityChart").getContext("2d");
    if (chartInstance) chartInstance.destroy();

    chartInstance = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label: selectedMode === "bikes" ? "Vélos disponibles (moyenne)" : "Docks disponibles (moyenne)",
          data: values,
          backgroundColor: "rgba(25,118,210,0.6)",
          borderColor: "rgba(25,118,210,1)",
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        scales: {
          y: { beginAtZero: true },
          x: { title: { display: true, text: "Heure" } }
        }
      }
    });
  } catch (err) {
    console.error("Erreur graphique :", err);
  }
}

// === RECHERCHE D’ADRESSE ===
async function searchAddress() {
  const address = document.getElementById("address").value.trim();
  if (!address) return alert("Veuillez entrer une adresse");

  showLoader(true);
  try {
    const res = await fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(address)}`);
    const data = await res.json();
    if (!data.length) return alert("Adresse introuvable");

    const { lat, lon } = data[0];

    // Ajoute un marqueur BLEU pour la position recherchée
    if (window.searchMarker) map.removeLayer(window.searchMarker);
    window.searchMarker = L.marker([lat, lon], {
      icon: L.icon({
        iconUrl: 'https://maps.google.com/mapfiles/ms/icons/blue-dot.png',
        iconSize: [32, 32],
        iconAnchor: [16, 32],
      })
    }).addTo(map);

    map.setView([lat, lon], 15);

    // Calcul des distances
    const nearest = stationsData
      .map(s => ({
        ...s,
        distance: haversine(lat, lon, s.lat, s.lon)
      }))
      // Assurer l'unicité par station_id
      .filter((v, i, a) => a.findIndex(t => t.station_id === v.station_id) === i)
      .sort((a, b) => a.distance - b.distance)
      .slice(0, 5); // 5 plus proches

    updateSidebarWithNearest(nearest, lat, lon);
  } catch (err) {
    console.error(err);
  } finally {
    showLoader(false);
  }
}

function updateSidebarWithNearest(stations, refLat, refLon) {
  const list = document.getElementById("stationList");
  list.innerHTML = "";
  document.getElementById("sidebarTitle").textContent = "Stations à proximité";

  stations.forEach(station => {
    const li = document.createElement("li");
    const dist = haversine(refLat, refLon, station.lat, station.lon).toFixed(2);
    li.textContent = `${station.name} — ${station.num_bikes_available} vélos / ${station.num_docks_available} docks (${dist} km)`;
    li.onclick = () => selectStation(station);
    list.appendChild(li);
  });
}


// === DISTANCE HAVERSINE ===
function haversine(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) ** 2 +
            Math.cos(lat1 * Math.PI / 180) *
            Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.asin(Math.sqrt(a));
}

// === DÉMARRAGE ===
document.getElementById("applyFilters").addEventListener("click", loadStations);
document.getElementById("resetFilters").addEventListener("click", () => {
  document.getElementById("minBikes").value = 0;
  document.getElementById("minDocks").value = 0;
  document.getElementById("arrondissement").value = "";
  loadStations();
});

window.addEventListener("DOMContentLoaded", () => {
  loadStations(); // chargement initial
  updateChart();  // graphique global
});
