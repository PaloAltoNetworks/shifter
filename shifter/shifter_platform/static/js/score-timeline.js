/**
 * Score Timeline Chart
 *
 * Renders a stepped-line Chart.js chart showing cumulative score progression
 * for a CTF participant. Fetches data from the score-timeline API endpoint.
 *
 * Usage: call initScoreTimeline(canvasId, apiUrl) after Chart.js is loaded.
 */

/* global Chart */

function initScoreTimeline(canvasId, apiUrl) {
    var canvas = document.getElementById(canvasId);
    if (!canvas) return;

    fetch(apiUrl)
        .then(function (response) {
            return response.json();
        })
        .then(function (data) {
            if (!data.timeline || data.timeline.length === 0) {
                var parent = canvas.parentElement;
                parent.removeChild(canvas);
                parent.textContent = "No score data yet.";
                return;
            }

            var labels = [];
            var scores = [];
            var tooltipLabels = [];

            data.timeline.forEach(function (entry) {
                labels.push(new Date(entry.timestamp));
                scores.push(entry.cumulative);
                var pointsText =
                    entry.points > 0
                        ? " (+" + entry.points + ")"
                        : entry.points < 0
                          ? " (" + entry.points + ")"
                          : "";
                tooltipLabels.push(entry.label + pointsText);
            });

            new Chart(canvas, {
                type: "line",
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: "Score",
                            data: scores,
                            borderColor: "#94a3b8",
                            backgroundColor: "rgba(148, 163, 184, 0.1)",
                            fill: true,
                            stepped: "before",
                            pointRadius: 3,
                            pointBackgroundColor: "#94a3b8",
                            borderWidth: 2,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            type: "time",
                            time: {
                                tooltipFormat: "MMM d, HH:mm",
                                displayFormats: {
                                    hour: "HH:mm",
                                    day: "MMM d",
                                },
                            },
                            ticks: { color: "#b8b8b8" },
                            grid: { color: "rgba(255,255,255,0.1)" },
                        },
                        y: {
                            beginAtZero: true,
                            ticks: { color: "#b8b8b8", precision: 0 },
                            grid: { color: "rgba(255,255,255,0.1)" },
                        },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                afterLabel: function (context) {
                                    return tooltipLabels[context.dataIndex];
                                },
                            },
                        },
                    },
                },
            });
        })
        .catch(function (err) {
            console.error("Failed to load score timeline:", err);
        });
}
