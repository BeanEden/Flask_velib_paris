// Initialisation de la carte (Centrée sur Paris)
var map = L.map('map').setView([48.8566, 2.3522], 13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors'
}).addTo(map);

// Cluster Group (pour regrouper les 1500 points)
var markers = L.markerClusterGroup();
map.addLayer(markers);

// Variable pour le graphique Chart.js
var myChart = null;

// Fonction de chargement des données
function loadStations() {
    // Afficher loader
    document.getElementById('loader').style.display = 'block';

    // Récupérer les valeurs des filtres
    const minBikes = document.getElementById('minBikes').value;
    const minDocks = document.getElementById('minDocks').value;
    const arr = document.getElementById('arrondissement').value;

    // Appel API Flask
    const url = `/stations?min_bikes=${minBikes}&min_docks=${minDocks}&arrondissement=${arr}`;

    fetch(url)
        .then(response => response.json())
        .then(data => {
            markers.clearLayers(); // Nettoyer la carte

            data.forEach(station => {
                if(station.lat && station.lon) {
                    // Couleur icône selon dispo (Vert = OK, Rouge = Vide)
                    let color = station.num_bikes > 0 ? 'green' : 'red';
                    
                    let marker = L.marker([station.lat, station.lon], {
                        title: station.name
                    });

                    // Popup au clic
                    marker.bindPopup(`<b>${station.name}</b><br>🚲 Vélos: ${station.num_bikes}<br>🅿️ Bornes: ${station.num_docks}`);
                    
                    // Evénement clic pour charger le graph
                    marker.on('click', () => loadStationDetails(station));
                    
                    markers.addLayer(marker);
                }
            });
            
            document.getElementById('loader').style.display = 'none';
        })
        .catch(err => {
            console.error(err);
            document.getElementById('loader').innerText = "Erreur chargement";
        });
}

function loadStationDetails(station) {
    // Mise à jour sidebar
    const div = document.getElementById('station-info');
    div.innerHTML = `
        <h3>${station.name}</h3>
        <p>Code: ${station.station_code || station.station_id}</p>
        <p>Capacité: ${station.capacity}</p>
    `;
    
    document.getElementById('chartContainer').style.display = 'block';
    
    // Charger historique
    fetch(`/station_chart?station_id=${station.station_id}`)
        .then(res => res.json())
        .then(data => {
            updateChart(data);
        });
}

function updateChart(data) {
    const ctx = document.getElementById('availabilityChart').getContext('2d');
    
    const labels = data.map(d => d.time);
    const bikes = data.map(d => d.bikes);
    const docks = data.map(d => d.docks);

    if (myChart) {
        myChart.destroy();
    }

    myChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                { label: 'Vélos', data: bikes, borderColor: 'green', tension: 0.1 },
                { label: 'Bornes', data: docks, borderColor: 'blue', tension: 0.1 }
            ]
        }
    });
}

// Bouton Filtrer
document.getElementById('applyFilters').addEventListener('click', loadStations);

// Chargement initial
loadStations();