/*
 * Interactive Hand-Tracking LED Controller - Arduino Uno firmware
 * ---------------------------------------------------------------
 * Companion sketch for main.py. Receives newline-terminated ASCII
 * commands over USB serial and drives 5 PWM LEDs.
 *
 * Protocol (must match SerialProtocol in main.py):
 *   D,a0,a1,a2,a3,a4   -> set 5 finger angles 0..180 (mapped to PWM 0..255)
 *   G,n                -> play gesture animation n (1..6)
 *   I                  -> enter idle breathing-wave mode
 *
 * Gesture ids:
 *   1 = Fist        2 = Open Hand   3 = Thumbs Up
 *   4 = Thumbs Down 5 = One Finger  6 = Hang Loose
 *
 * Baud rate: 115200 (matches SerialConfig.baudrate in main.py).
 *
 * Wiring diagram is documented at the bottom of this file.
 */

// ----------------------- Configuration ------------------------------------
const uint8_t NUM_LEDS = 5;

// LED pins (all hardware-PWM "~" pins on the Uno).
// Index 0 -> LED1 (thumb) ... index 4 -> LED5 (pinky).
const uint8_t LED_PINS[NUM_LEDS] = {3, 5, 6, 9, 10};

const unsigned long BAUD_RATE   = 115200;
const unsigned long LINK_TIMEOUT_MS = 2000;  // fall back to idle if silent

// ----------------------- State --------------------------------------------
enum Mode { MODE_DATA, MODE_IDLE };
Mode currentMode = MODE_DATA;

uint8_t ledLevel[NUM_LEDS] = {0, 0, 0, 0, 0};  // current PWM duty (0..255)

char    lineBuf[48];
uint8_t lineLen = 0;

unsigned long lastCommandMs = 0;

// ----------------------- Low-level LED helpers -----------------------------

// Write a PWM duty value to a single LED.
void setLed(uint8_t idx, uint8_t value) {
  if (idx < NUM_LEDS) {
    ledLevel[idx] = value;
    analogWrite(LED_PINS[idx], value);
  }
}

// Turn every LED fully off.
void allOff() {
  for (uint8_t i = 0; i < NUM_LEDS; i++) setLed(i, 0);
}

// Turn every LED to a common brightness.
void allOn(uint8_t value) {
  for (uint8_t i = 0; i < NUM_LEDS; i++) setLed(i, value);
}

// Map an incoming angle (0..180) to a PWM duty (0..255).
uint8_t angleToPwm(long angle) {
  if (angle < 0)   angle = 0;
  if (angle > 180) angle = 180;
  return (uint8_t)map(angle, 0, 180, 0, 255);
}

// Flush any bytes that arrived while a blocking animation was running so we
// never act on a stale or partial command afterwards.
void flushSerialInput() {
  while (Serial.available() > 0) Serial.read();
  lineLen = 0;
}

// ----------------------- Gesture animations --------------------------------
// Each animation is short (< ~1s) so it always finishes inside the Python
// gesture cooldown window, during which Python pauses normal data frames.

// Gesture 1 - Fist: LED3, LED1, LED5, LED2, LED4 in sequence, then all off.
void gestureFist() {
  const uint8_t order[NUM_LEDS] = {2, 0, 4, 1, 3};  // 0-based LED indices
  allOff();
  for (uint8_t i = 0; i < NUM_LEDS; i++) {
    setLed(order[i], 255);
    delay(70);
  }
  delay(80);
  allOff();
}

// Gesture 2 - Open Hand: all LEDs together with a fast double blink.
void gestureOpenHand() {
  for (uint8_t b = 0; b < 2; b++) {
    allOn(255);
    delay(90);
    allOff();
    delay(90);
  }
}

// Gesture 3 - Thumbs Up: LED1,LED2,LED3 in sequence, then LED4+LED5 together.
void gestureThumbsUp() {
  allOff();
  for (uint8_t i = 0; i < 3; i++) {
    setLed(i, 255);
    delay(90);
  }
  setLed(3, 255);
  setLed(4, 255);
  delay(220);
  allOff();
}

// Gesture 4 - Thumbs Down: LED5,LED4,LED3 in sequence, then LED2+LED1 together.
void gestureThumbsDown() {
  allOff();
  for (int8_t i = 4; i >= 2; i--) {
    setLed((uint8_t)i, 255);
    delay(90);
  }
  setLed(1, 255);
  setLed(0, 255);
  delay(220);
  allOff();
}

// Gesture 5 - One Finger: LED3 blinks fast 5 times alone.
void gestureOneFinger() {
  allOff();
  for (uint8_t i = 0; i < 5; i++) {
    setLed(2, 255);
    delay(70);
    setLed(2, 0);
    delay(70);
  }
}

// Gesture 6 - Hang Loose: a wave LED1->LED5 then LED5->LED1, repeated.
void gestureHangLoose() {
  for (uint8_t rep = 0; rep < 2; rep++) {
    for (uint8_t i = 0; i < NUM_LEDS; i++) {
      allOff();
      setLed(i, 255);
      delay(55);
    }
    for (int8_t i = NUM_LEDS - 2; i >= 0; i--) {
      allOff();
      setLed((uint8_t)i, 255);
      delay(55);
    }
  }
  allOff();
}

// Dispatch a gesture by id.
void playGesture(uint8_t id) {
  switch (id) {
    case 1: gestureFist();       break;
    case 2: gestureOpenHand();   break;
    case 3: gestureThumbsUp();   break;
    case 4: gestureThumbsDown(); break;
    case 5: gestureOneFinger();  break;
    case 6: gestureHangLoose();  break;
    default: break;
  }
  flushSerialInput();
  currentMode = MODE_DATA;
}

// ----------------------- Idle breathing-wave mode --------------------------
// Non-blocking: produces a soft brightness wave that breathes across the
// LEDs. Each LED is phase-shifted so the wave travels along the strip.
void updateIdle() {
  unsigned long t = millis();
  for (uint8_t i = 0; i < NUM_LEDS; i++) {
    // 2*PI period ~ 2.6s; 0.9 rad phase shift per LED creates a travelling wave.
    float phase = (t / 1300.0f * PI) + i * 0.9f;
    float s = (sin(phase) + 1.0f) * 0.5f;   // 0..1
    setLed(i, (uint8_t)(s * 255.0f));
  }
}

// ----------------------- Command parsing -----------------------------------

// Parse a complete line (without the trailing newline) and act on it.
void handleLine(char *line) {
  if (line[0] == '\0') return;

  if (line[0] == 'I') {                 // Idle request
    currentMode = MODE_IDLE;
    return;
  }

  if (line[0] == 'G') {                 // Gesture request: "G,n"
    char *comma = strchr(line, ',');
    if (comma != NULL) {
      uint8_t id = (uint8_t)atoi(comma + 1);
      playGesture(id);
    }
    return;
  }

  if (line[0] == 'D') {                 // Data frame: "D,a0,a1,a2,a3,a4"
    currentMode = MODE_DATA;
    char *token = strtok(line + 1, ",");  // skip 'D'
    uint8_t idx = 0;
    while (token != NULL && idx < NUM_LEDS) {
      long angle = atol(token);
      setLed(idx, angleToPwm(angle));
      idx++;
      token = strtok(NULL, ",");
    }
    return;
  }
}

// Read available serial bytes and assemble newline-terminated lines.
void readSerial() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    lastCommandMs = millis();
    if (c == '\n' || c == '\r') {
      if (lineLen > 0) {
        lineBuf[lineLen] = '\0';
        handleLine(lineBuf);
        lineLen = 0;
      }
    } else if (lineLen < sizeof(lineBuf) - 1) {
      lineBuf[lineLen++] = c;
    } else {
      // Overflow guard: drop the malformed line.
      lineLen = 0;
    }
  }
}

// ----------------------- Arduino entry points -------------------------------
void setup() {
  for (uint8_t i = 0; i < NUM_LEDS; i++) {
    pinMode(LED_PINS[i], OUTPUT);
    analogWrite(LED_PINS[i], 0);
  }
  Serial.begin(BAUD_RATE);
  lastCommandMs = millis();

  // Brief startup self-test: sweep the LEDs once.
  for (uint8_t i = 0; i < NUM_LEDS; i++) {
    setLed(i, 255);
    delay(60);
    setLed(i, 0);
  }
}

void loop() {
  readSerial();

  // If the host has been silent for a while, fall back to idle breathing.
  if (millis() - lastCommandMs > LINK_TIMEOUT_MS) {
    currentMode = MODE_IDLE;
  }

  if (currentMode == MODE_IDLE) {
    updateIdle();
    delay(8);  // ~125 Hz update, smooth breathing without flicker
  }
  // In MODE_DATA the LED levels are held from the last 'D' frame.
}

/*
 * ===========================================================================
 * ARDUINO UNO WIRING DIAGRAM  (5 LEDs, 5 x 220 ohm resistors, 6 wires)
 * ===========================================================================
 *
 *   LED #   Color (suggested)   Arduino PWM Pin   Finger
 *   -----   -----------------   ---------------   ------
 *   LED1    Red                 D3  (~)           Thumb
 *   LED2    Green               D5  (~)           Index
 *   LED3    Blue                D6  (~)           Middle
 *   LED4    Yellow              D9  (~)           Ring
 *   LED5    White               D10 (~)           Pinky
 *
 *   Each LED:  Arduino PWM pin --> [220 ohm resistor] --> LED anode (+)
 *              LED cathode (-) --> common GND rail --> Arduino GND
 *
 *   Wiring (6 wires total): 5 signal wires (D3, D5, D6, D9, D10) + 1 GND wire
 *   from the breadboard ground rail back to an Arduino GND pin.
 *
 *       D3  ---[220R]---|>|---+
 *       D5  ---[220R]---|>|---+
 *       D6  ---[220R]---|>|---+---> GND rail ---> Arduino GND
 *       D9  ---[220R]---|>|---+
 *       D10 ---[220R]---|>|---+
 *
 *   All of D3, D5, D6, D9, D10 are hardware-PWM (~) pins, so each LED's
 *   brightness is controlled independently with analogWrite().
 * ===========================================================================
 */
