// === INITIALISATION ===
let map = L.map('map').setView([48.8566, 2.3522], 13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap'
}).addTo(map);

let markersLayer = L.layerGroup().addTo(map); // <-- layerGroup simple
let stationsData = [];
let selectedMode = "bikes";
let currentChart = null;


// === OUTILS ===
function showLoader(show) {
  document.getElementById("loader").style.display = show ? "block" : "none";
}

function getMarkerIcon(bikes) {
  let color;
  if (bikes === 0) color = 'red';
  else if (bikes <= 3) color = 'orange';
  else color = 'green';

  return L.icon({
    iconUrl: `https://maps.google.com/mapfiles/ms/icons/${color}-dot.png`,
    iconSize: [32, 32],
    iconAnchor: [16, 32],
    popupAnchor: [0, -30]
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
  const filtered = document.getElementById("minBikes").value || document.getElementById("minDocks").value || document.getElementById("arrondissement").value;
  updateSidebar(null, filtered); 
    updateGlobalChart();
  } catch (err) {
    console.error("Erreur chargement stations:", err);
  } finally {
    showLoader(false);
  }
}
function sortStations(stations, mode, filtered=false) {
  if (!filtered) {
    // Par défaut (pas de filtre) : ordre alphabétique
    return [...stations].sort((a, b) => a.name.localeCompare(b.name));
  } else {
    // Avec filtre : ordre décroissant de vélos ou bornes selon mode
    return [...stations].sort((a, b) => {
      const valA = mode === "bikes" ? a.num_bikes_available : a.num_docks_available;
      const valB = mode === "bikes" ? b.num_bikes_available : b.num_docks_available;
      return valB - valA;
    });
  }
}

// === MISE À JOUR DES MARQUEURS ===
function getMarkerIcon(value) {
  let color;
  if (value === 0) color = 'red';
  else if (value <= 3) color = 'orange';
  else color = 'green';

  // Marker standard Leaflet via L.Icon
  return L.icon({
    iconUrl: `https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-${color}.png`,
    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
    iconSize: [25, 41],       // taille de l'icône
    iconAnchor: [12, 41],     // point qui correspond à la position
    popupAnchor: [1, -34],    // où s'ouvre le popup
    shadowSize: [41, 41]
  });
}

// === MISE À JOUR DES MARQUEURS ===
function updateMap() {
  markersLayer.clearLayers(); // on vide le layer avant de rajouter
  stationsData.forEach(station => {
    const lat = parseFloat(station.lat);
    const lon = parseFloat(station.lon);
    if (isNaN(lat) || isNaN(lon)) return;

    const value = selectedMode === "bikes" ? (station.num_bikes_available || 0) : (station.num_docks_available || 0);

    const marker = L.marker([lat, lon], { icon: getMarkerIcon(value) })
      .bindPopup(`<b>${station.name}</b><br>🚲 Vélos: ${station.num_bikes_available}<br>🅿️ Docks: ${station.num_docks_available}`)
      .on("click", () => selectStation(station));

    markersLayer.addLayer(marker); // ajout classique
  });
}



// === PANNEAU LATÉRAL : afficher toutes les stations avec leur dernier état ===
function updateSidebar(selectedStation = null) {
  const list = document.getElementById("stationList");
  list.innerHTML = "";

  let stationsToShow = [];

  if (selectedStation) {
    // Cas : une station est sélectionnée → on n’affiche que son détail
    stationsToShow = [selectedStation];
    document.getElementById("sidebarTitle").textContent = `Détails : ${selectedStation.name}`;
  } else {
    // Déduplication par station_id
    const uniqueStationsMap = {};
    stationsData.forEach(s => { uniqueStationsMap[s.station_id] = s; });
    let uniqueStations = Object.values(uniqueStationsMap);

    // Récupérer les valeurs de filtre
    const minBikes = parseInt(document.getElementById("minBikes").value) || 0;
    const minDocks = parseInt(document.getElementById("minDocks").value) || 0;
    const arrondissement = document.getElementById("arrondissement").value.toLowerCase().trim();

    // Appliquer les filtres
    const filtered = uniqueStations.filter(s => 
      (s.num_bikes_available || 0) >= minBikes &&
      (s.num_docks_available || 0) >= minDocks &&
      (arrondissement ? s.name.toLowerCase().includes(arrondissement) : true)
    );

    // Choisir le tri
    const hasFilter = minBikes > 0 || minDocks > 0 || arrondissement !== "";
    if (hasFilter) {
      // Tri décroissant selon le mode choisi
      stationsToShow = filtered.sort((a, b) => {
        const valA = selectedMode === "bikes" ? a.num_bikes_available : a.num_docks_available;
        const valB = selectedMode === "bikes" ? b.num_bikes_available : b.num_docks_available;
        return valB - valA;
      });
      document.getElementById("sidebarTitle").textContent = `Stations filtrées (${selectedMode === "bikes" ? "vélos" : "bornes"} disponibles)`;
    } else {
      // Pas de filtre → ordre alphabétique
      stationsToShow = uniqueStations.sort((a, b) => a.name.localeCompare(b.name));
      document.getElementById("sidebarTitle").textContent = "Stations visibles sur la carte";
    }
  }

  // Affichage dans la sidebar
  stationsToShow.forEach(station => {
    const li = document.createElement("li");
    li.textContent = `${station.name} — 🚲 ${station.num_bikes_available || 0} vélos / 🅿️ ${station.num_docks_available || 0} docks`;

    li.addEventListener("click", () => {
      map.setView([station.lat, station.lon], 15);
      selectStation(station); // met à jour le détail + graphique
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
  const filtered = document.getElementById("minBikes").value || document.getElementById("minDocks").value || document.getElementById("arrondissement").value;
  updateSidebar(null, filtered);
  updateChart();
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
    map.setView([lat, lon], 15);

    // Trouve les 3 plus proches stations
    const nearest = stationsData
      .map(s => ({
        ...s,
        distance: haversine(lat, lon, s.lat, s.lon)
      }))
      .sort((a, b) => a.distance - b.distance)
      .slice(0, 3);

    updateSidebarWithNearest(nearest);
  } catch (err) {
    console.error(err);
  } finally {
    showLoader(false);
  }
}

function updateSidebarWithNearest(stations) {
  const list = document.getElementById("stationList");
  list.innerHTML = "";
  document.getElementById("sidebarTitle").textContent = "Stations à proximité";

  stations.forEach(station => {
    const li = document.createElement("li");
    li.textContent = `${station.name} — ${station.num_bikes_available} vélos / ${station.num_docks_available} docks`;
    li.onclick = () => selectStation(station);
    list.appendChild(li);
  });
}

// === DISTANCE HAVERSINE ===
function haversine(lat1, lon1, lat2, lon2) {
  const R = 6371;
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * Math.PI / 180) *
    Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.asin(Math.sqrt(a));
}

// === SÉLECTION D’UNE STATION ===
function selectStation(station) {
  map.setView([station.lat, station.lon], 15);
  updateChart(station);
  updateSidebar(station); // affiche le détail de la station sélectionnée
}


// === GRAPHIQUE DISPONIBILITÉ ===
async function updateChart(station) {
  const ctx = document.getElementById("availabilityChart").getContext("2d");
  if (currentChart) currentChart.destroy();

  let dataset = [];
  if (!station) {
    // Optionnel : global pour toutes les stations
    dataset = await fetchGlobalHourlyAverage();
  } else {
    const res = await fetch(`/station_chart?station_id=${station.station_id}&mode=${selectedMode}`);
    dataset = await res.json();
  }

  const labels = dataset.map(d => d.hour + "h");
  const values = dataset.map(d => d.avg);

  currentChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: selectedMode === "bikes" ? "Vélos disponibles" : "Bornes disponibles",
        data: values,
        borderColor: "#1976d2",
        backgroundColor: "rgba(25,118,210,0.2)",
        tension: 0.3
      }]
    },
    options: {
      scales: {
        y: { beginAtZero: true },
        x: { title: { display: true, text: "Heure" } }
      }
    }
  });
}

// Pour affichage global si besoin
async function fetchGlobalHourlyAverage() {
  const res = await fetch(`/station_chart?mode=${selectedMode}`);
  return await res.json();
}

function computeGlobalHourlyAverage(stations) {
  const byHour = {};
  stations.forEach(s => {
    (s.history || []).forEach(h => {
      const hour = new Date(h.timestamp).getHours();
      const value = selectedMode === "bikes" ? h.num_bikes_available : h.num_docks_available;
      byHour[hour] = byHour[hour] || [];
      byHour[hour].push(value);
    });
  });
  return Object.entries(byHour).map(([h, vals]) => ({
    hour: +h,
    avg: vals.reduce((a,b)=>a+b,0)/vals.length
  })).sort((a,b)=>a.hour-b.hour);
}

// === DÉMARRAGE ===
document.getElementById("applyFilters").addEventListener("click", loadStations);
document.getElementById("resetFilters").addEventListener("click", () => {
  document.getElementById("minBikes").value = 0;
  document.getElementById("minDocks").value = 0;
  document.getElementById("arrondissement").value = "";
  loadStations();
});

// Chargement initial
loadStations();
