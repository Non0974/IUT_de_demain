// CampusTwin — nœud porte (Seeed XIAO ESP32S3) : compter les entrées et sorties sans caméra.
// Trois capteurs regardent la porte, chacun donne son avis sur chaque passage :
//  - VL53L5CX (ToF 8x8, au plafond au-dessus de la porte)      bus I2C 0 : D4 (SDA), D5 (SCL)
//  - MLX90640 (thermique 32x24, à côté du ToF)                  bus I2C 1 : D8 (SDA), D9 (SCL)
//  - HLK-LD2450 (radar, sur le mur côté salle)                   UART : D7 (RX), D6 (TX), 256000 bauds
// Le ToF et la caméra thermique voient la porte coupée en deux : côté couloir et côté salle.
// Une personne qui passe allume d'abord un côté puis l'autre : c'est le sens du passage. Le nombre
// de silhouettes donne le nombre de personnes (deux personnes de front). Le radar donne le sens par
// la vitesse des cibles près de la porte, et dit s'il reste quelqu'un dans la salle.
// Fusion : vote à la majorité dans une fenêtre de 1,5 s.
// Bibliothèques : SparkFun VL53L5CX, Adafruit MLX90640.

#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <time.h>
#include <SparkFun_VL53L5CX_Library.h>
#include <Adafruit_MLX90640.h>
#include "config.h"

TwoWire busThermique(1);
SparkFun_VL53L5CX tof;
VL53L5CX_ResultsData mesureTof;
Adafruit_MLX90640 mlx;

// ---------- types (en haut du fichier : Arduino ajoute les déclarations des fonctions avant le code) ----------
struct Passage { int sens; int n; unsigned long t; };   // sens +1 entrée, -1 sortie ; n personnes

struct Detecteur {
  bool enCours = false;
  int premiere = -1;     // 0 couloir, 1 salle
  int derniere = -1;
  int maxPersonnes = 0;
};

enum { TOF = 0, THERMIQUE = 1 };
struct Evenement { int capteur; Passage p; };          // un avis d'un capteur sur un passage

struct Cible { int x, y, vitesse; bool active; };      // une cible du radar (mm, cm/s)

// ---------- envoi au serveur (file d'attente si le réseau ne répond pas) ----------
struct Message { String json; unsigned long cree; };
const int TAILLE_FILE = 80;
Message file_[TAILLE_FILE];
int debutFile = 0, nbFile = 0;

void mettreEnFile(const String &json) {
  if (nbFile == TAILLE_FILE) { debutFile = (debutFile + 1) % TAILLE_FILE; nbFile--; }
  file_[(debutFile + nbFile) % TAILLE_FILE] = { json, millis() };
  nbFile++;
}

String horodater(const Message &m) {
  String j = m.json.substring(0, m.json.length() - 1);
  if (time(nullptr) > 1700000000) j += ",\"t\":" + String((double)time(nullptr) - (millis() - m.cree) / 1000.0, 1);
  else j += ",\"age_ms\":" + String(millis() - m.cree);
  return j + "}";
}

void viderFile() {
  if (WiFi.status() != WL_CONNECTED) return;
  while (nbFile > 0) {
    HTTPClient http;
    http.begin(String(SERVEUR_URL) + "/api/mesure");
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-Cle", CLE_CAPTEURS);
    http.setTimeout(3000);
    int code = http.POST(horodater(file_[debutFile]));
    http.end();
    if (code < 200 || code >= 500) return;
    debutFile = (debutFile + 1) % TAILLE_FILE;
    nbFile--;
  }
}

// ---------- détection d'un passage sur une grille (ToF ou thermique) ----------

// Nombre de silhouettes : groupes de pixels voisins allumés (au moins tailleMin pixels)
int silhouettes(const bool *masque, int largeur, int hauteur, int tailleMin) {
  static int pile[768];
  static bool vu[768];
  int n = 0;
  for (int i = 0; i < largeur * hauteur; i++) vu[i] = false;
  for (int i = 0; i < largeur * hauteur; i++) {
    if (!masque[i] || vu[i]) continue;
    int taille = 0, haut = 0;
    pile[haut++] = i;
    vu[i] = true;
    while (haut) {
      int p = pile[--haut];
      taille++;
      int x = p % largeur, y = p / largeur;
      const int dx[4] = { 1, -1, 0, 0 }, dy[4] = { 0, 0, 1, -1 };
      for (int k = 0; k < 4; k++) {
        int nx = x + dx[k], ny = y + dy[k];
        if (nx < 0 || ny < 0 || nx >= largeur || ny >= hauteur) continue;
        int q = ny * largeur + nx;
        if (masque[q] && !vu[q]) { vu[q] = true; pile[haut++] = q; }
      }
    }
    if (taille >= tailleMin) n++;
  }
  return n;
}

// À chaque image : y a-t-il quelqu'un côté couloir, côté salle, et combien de silhouettes.
// Quand le champ redevient vide, on regarde d'où la personne est venue et où elle est allée.
Passage majDetecteur(Detecteur &d, bool couloir, bool salle, int nb) {
  Passage p = { 0, 0, 0 };
  int zone = couloir && !salle ? 0 : (salle && !couloir ? 1 : -1);
  if (couloir || salle) {
    if (!d.enCours) { d.enCours = true; d.premiere = zone; d.derniere = zone; d.maxPersonnes = 0; }
    if (d.premiere < 0) d.premiere = zone;
    if (zone >= 0) d.derniere = zone;
    d.maxPersonnes = max(d.maxPersonnes, nb);
  } else if (d.enCours) {
    d.enCours = false;
    if (d.premiere == 0 && d.derniere == 1) p = { +1, max(1, d.maxPersonnes), millis() };
    if (d.premiere == 1 && d.derniere == 0) p = { -1, max(1, d.maxPersonnes), millis() };
    // sinon : la personne a fait demi-tour, pas de passage
  }
  return p;
}

// ---------- événements des capteurs, mis en commun pour la fusion ----------
QueueHandle_t evenements;

// ---------- ToF ----------
float solTof[64];
Detecteur detTof;

void calibrerTof() {
  // Le sol vu à vide, mesuré au démarrage (personne sous la porte pendant 3 s)
  for (int i = 0; i < 64; i++) solTof[i] = 0;
  int n = 0;
  while (n < 30) {
    if (tof.isDataReady() && tof.getRangingData(&mesureTof)) {
      for (int i = 0; i < 64; i++) solTof[i] += mesureTof.distance_mm[i];
      n++;
    }
    delay(5);
  }
  for (int i = 0; i < 64; i++) solTof[i] /= n;
}

void lireTof() {
  if (!tof.isDataReady() || !tof.getRangingData(&mesureTof)) return;
  bool masque[64];
  bool couloir = false, salle = false;
  for (int i = 0; i < 64; i++) {
    uint8_t statut = mesureTof.target_status[i];
    bool valide = statut == 5 || statut == 9;
    masque[i] = valide && mesureTof.distance_mm[i] < solTof[i] - SEUIL_TOF_MM;
    if (!masque[i]) continue;
    bool basDeGrille = (i / 8) >= 4;
    if (basDeGrille == (TOF_SALLE_EN_BAS == 1)) salle = true; else couloir = true;
  }
  Passage p = majDetecteur(detTof, couloir, salle, silhouettes(masque, 8, 8, 2));
  if (p.sens) {
    Evenement e = { TOF, p };
    xQueueSend(evenements, &e, 0);
  }
}

// ---------- caméra thermique (dans sa propre tâche : une image prend ~120 ms) ----------
float image[768];
float fond[768];
Detecteur detThermique;
volatile bool presenceThermique = false;

void tacheThermique(void *) {
  // Fond appris au démarrage, puis mis à jour lentement là où il n'y a personne
  for (int i = 0; i < 768; i++) fond[i] = 0;
  for (int k = 0; k < 10; k++) {
    while (mlx.getFrame(image) != 0) delay(10);
    for (int i = 0; i < 768; i++) fond[i] += image[i] / 10;
  }
  static bool masque[768];
  for (;;) {
    if (mlx.getFrame(image) != 0) { delay(10); continue; }
    bool couloir = false, salle = false;
    for (int i = 0; i < 768; i++) {
      masque[i] = image[i] > fond[i] + SEUIL_THERMIQUE_C;
      if (masque[i]) {
        bool bas = (i / 32) >= 12;
        if (bas == (THERMIQUE_SALLE_EN_BAS == 1)) salle = true; else couloir = true;
      } else {
        fond[i] += (image[i] - fond[i]) * 0.01;   // le fond suit lentement le chauffage de la pièce
      }
    }
    presenceThermique = couloir || salle;
    Passage p = majDetecteur(detThermique, couloir, salle, silhouettes(masque, 32, 24, 6));
    if (p.sens) {
      Evenement e = { THERMIQUE, p };
      xQueueSend(evenements, &e, 0);
    }
  }
}

// ---------- radar LD2450 ----------
Cible cibles[3];
unsigned long dernierRadar = 0;
uint8_t trame[30];
int posTrame = 0;

int16_t valeurRadar(uint8_t bas, uint8_t haut) {
  // Format LD2450 : bit de poids fort = signe (1 = positif), 15 bits de valeur
  uint16_t brut = bas | (haut << 8);
  int16_t v = brut & 0x7FFF;
  return (brut & 0x8000) ? v : -v;
}

void lireRadar() {
  while (Serial1.available()) {
    uint8_t c = Serial1.read();
    // une trame : AA FF 03 00, 3 cibles de 8 octets, 55 CC
    const uint8_t entete[4] = { 0xAA, 0xFF, 0x03, 0x00 };
    if (posTrame < 4 && c != entete[posTrame]) { posTrame = (c == 0xAA) ? 1 : 0; continue; }
    trame[posTrame++] = c;
    if (posTrame < 30) continue;
    posTrame = 0;
    if (trame[28] != 0x55 || trame[29] != 0xCC) continue;
    for (int k = 0; k < 3; k++) {
      const uint8_t *b = trame + 4 + 8 * k;
      cibles[k].x = valeurRadar(b[0], b[1]);
      cibles[k].y = valeurRadar(b[2], b[3]);
      cibles[k].vitesse = valeurRadar(b[4], b[5]);
      cibles[k].active = b[0] | b[1] | b[2] | b[3];
    }
    dernierRadar = millis();
  }
}

// Avis du radar sur le sens : vitesse des cibles à moins de 1,5 m (+1 entre, -1 sort, 0 ne sait pas)
int avisRadar() {
  if (millis() - dernierRadar > 1000) return 0;
  int somme = 0;
  for (auto &c : cibles) if (c.active && abs(c.y) < 1500 && abs(c.vitesse) > 10) somme += (c.vitesse > 0 ? 1 : -1) * RADAR_SIGNE;
  return somme > 0 ? 1 : (somme < 0 ? -1 : 0);
}

bool presenceRadar() {
  if (millis() - dernierRadar > 2000) return false;
  for (auto &c : cibles) if (c.active) return true;
  return false;
}

// ---------- fusion ----------
Evenement attente[10];
int nbAttente = 0;
unsigned long debutFenetre = 0;
int avisRadarFenetre = 0;

void fusionner() {
  Evenement e;
  while (xQueueReceive(evenements, &e, 0) == pdTRUE) {
    if (nbAttente == 0) { debutFenetre = millis(); avisRadarFenetre = 0; }
    if (nbAttente < 10) attente[nbAttente++] = e;
  }
  if (nbAttente == 0) return;
  int r = avisRadar();
  if (r) avisRadarFenetre = r;
  if (millis() - debutFenetre < FENETRE_FUSION_MS) return;

  // Votes : chaque capteur vote pour le sens qu'il a vu le plus ; le radar vote aussi
  int personnes[2][2] = { { 0, 0 }, { 0, 0 } };   // [capteur][0 = entrée, 1 = sortie]
  for (int i = 0; i < nbAttente; i++) personnes[attente[i].capteur][attente[i].p.sens > 0 ? 0 : 1] += attente[i].p.n;
  int votes = 0, avis = 0;
  for (int c = 0; c < 2; c++) {
    int v = personnes[c][0] > personnes[c][1] ? 1 : (personnes[c][1] > personnes[c][0] ? -1 : 0);
    if (v) { votes += v; avis++; }
  }
  if (avisRadarFenetre) { votes += avisRadarFenetre; avis++; }
  nbAttente = 0;
  if (votes == 0) return;                          // capteurs en désaccord : on ne compte rien
  int sens = votes > 0 ? 1 : -1;
  int col = sens > 0 ? 0 : 1;
  int n = max(personnes[TOF][col], personnes[THERMIQUE][col]);
  if (n == 0) return;
  float confiance = (float)abs(votes) / avis;
  for (int i = 0; i < n; i++) {
    mettreEnFile("{\"type\":\"passage\",\"salle\":\"" SALLE "\",\"sens\":" + String(sens) + ",\"confiance\":" + String(confiance, 2) + "}");
  }
  Serial.printf("Passage : %s x%d (confiance %.2f)\n", sens > 0 ? "entrée" : "sortie", n, confiance);
}

// ---------- programme ----------

void connecterWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_NOM, WIFI_MOT_DE_PASSE);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
}

void setup() {
  Serial.begin(115200);
  evenements = xQueueCreate(20, sizeof(Evenement));

  Wire.begin();
  Wire.setClock(1000000);
  if (!tof.begin()) Serial.println("VL53L5CX introuvable : vérifier le câblage");   // ~10 s : envoi du firmware du capteur
  tof.setResolution(8 * 8);
  tof.setRangingFrequency(15);
  tof.startRanging();
  calibrerTof();

  busThermique.begin(D8, D9, 800000);
  if (!mlx.begin(MLX90640_I2CADDR_DEFAULT, &busThermique)) Serial.println("MLX90640 introuvable : vérifier le câblage");
  mlx.setMode(MLX90640_CHESS);
  mlx.setResolution(MLX90640_ADC_18BIT);
  mlx.setRefreshRate(MLX90640_16_HZ);
  xTaskCreatePinnedToCore(tacheThermique, "thermique", 8192, nullptr, 1, nullptr, 0);

  Serial1.begin(256000, SERIAL_8N1, D7, D6);

  connecterWifi();
  configTime(0, 0, NTP_SERVEUR);
}

unsigned long dernierePresence = 0;
bool presenceEnvoyee = false;

void loop() {
  connecterWifi();
  lireTof();
  lireRadar();
  fusionner();

  // Présence (radar ou silhouettes) : toutes les 30 s, ou tout de suite si elle change.
  // Le serveur remet le compteur à zéro après 2 min sans présence (passages ratés à la sortie).
  bool presence = presenceRadar() || presenceThermique || detTof.enCours;
  if (presence != presenceEnvoyee || millis() - dernierePresence > 30000) {
    mettreEnFile(String("{\"type\":\"presence\",\"salle\":\"" SALLE "\",\"presence\":") + (presence ? "true" : "false") + "}");
    presenceEnvoyee = presence;
    dernierePresence = millis();
  }
  viderFile();
}
