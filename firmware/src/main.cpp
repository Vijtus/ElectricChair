#include <Arduino.h>
#include "SoftwareSerial.h"

typedef struct {
    const char *name;
    unsigned char code;
} CommandMap;

static const CommandMap command_map[] = {
    { "ramiona", 0x13 },                // Ramiona
    { "przedramiona", 0x12 },           // Przedramiona
    { "nogi", 0x11 },                   // Nogi
    { "sila_nacisku_plus", 0x10 },      // Siła nacisku (+)
    { "sila_nacisku_minus", 0x0F },     // Siła nacisku (-)
    { "masaz_posladkow", 0x0E },        // Masaż pośladków
    { "masaz_stop", 0x0D },             // Masaż stóp
    { "predkosc_masazu_stop", 0x02 },   // Prędkość masażu stóp
    { "pauza", 0x0B },                  // Pauza
    { "ogrzewanie", 0x03 },             // Ogrzewanie
    { "czas", 0x07 },                   // Czas
    { "masaz_calego_ciala", 0x04 },     // Masaż całego ciała
    { "grawitacja_zero", 0x08 },        // Grawitacja zero
    { "tryb_automatyczny", 0x05 },      // Tryb Automatyczny
    { "oparcie_w_gore", 0x09 },         // Oparcie w górę
    { "oparcie_w_dol", 0x06 },          // Oparcie w dół
    { "predkosc_minus", 0x14 },         // Prędkość (-)
    { "predkosc_plus", 0x15 },          // Prędkość (+)
    { "do_przodu_do_tylu_1", 0x16 },    // Do przodu/do tyłu
    { "plecy_i_talia", 0x17 },          // Plecy i talia
    { "do_przodu_do_tylu_2", 0x18 },    // Do przodu/do tyłu
    { "szyja", 0x19 },                  // Szyja 
    { "power", 0x01 }                   // POWER
};

static SoftwareSerial mySerial(10, 11); // RX, TX
static unsigned char pending_command = 0x00;
static bool has_pending_command = false;
static String command_buffer;
static unsigned long last_send_ms = 0;
static bool chair_read_enabled = false;

static void print_hex_byte(unsigned char value) {
    Serial.print("0x");
    if (value < 0x10) {
        Serial.print('0');
    }
    Serial.print(value, HEX);
}

static bool handle_control_command(const String &cmd) {
    if (cmd.equalsIgnoreCase("listen") || cmd.equalsIgnoreCase("listen toggle")) {
        chair_read_enabled = !chair_read_enabled;
        Serial.print("Chair read: ");
        Serial.println(chair_read_enabled ? "ON" : "OFF");
        return true;
    }
    if (cmd.equalsIgnoreCase("listen on")) {
        chair_read_enabled = true;
        Serial.println("Chair read: ON");
        return true;
    }
    if (cmd.equalsIgnoreCase("listen off")) {
        chair_read_enabled = false;
        Serial.println("Chair read: OFF");
        return true;
    }
    return false;
}

static bool lookup_command(const String &name, unsigned char &code) {
    for (size_t i = 0; i < (sizeof(command_map) / sizeof(command_map[0])); ++i) {
        if (name.equalsIgnoreCase(command_map[i].name)) {
            code = command_map[i].code;
            return true;
        }
    }
    return false;
}

static void handle_serial_input() {
    while (Serial.available() > 0) {
        char ch = static_cast<char>(Serial.read());
        if (ch == '\n' || ch == '\r') {
            if (command_buffer.length() > 0) {
                unsigned char code = 0x00;
                String cmd = command_buffer;
                cmd.trim();
                if (handle_control_command(cmd)) {
                    command_buffer = "";
                    continue;
                }
                if (lookup_command(cmd, code)) {
                    pending_command = code;
                    has_pending_command = true;
                    Serial.print("Queued: ");
                    Serial.print(cmd);
                    Serial.print(" -> 0x");
                    if (code < 0x10) {
                        Serial.print('0');
                    }
                    Serial.println(code, HEX);
                } else {
                    Serial.print("Unknown command: ");
                    Serial.println(cmd);
                }
                command_buffer = "";
            }
        } else {
            command_buffer += ch;
        }
    }
}

static void send_periodic() {
    unsigned long now = millis();
    if (now - last_send_ms < 100) {
        return;
    }
    last_send_ms = now;

    unsigned char out = 0x00;
    if (has_pending_command) {
        out = pending_command;
        has_pending_command = false;
        pending_command = 0x00;
    }
    mySerial.write(out);
}

static void read_chair_data() {
    if (!chair_read_enabled) {
        return;
    }

    // Limit per-loop read to keep command input responsive.
    for (int i = 0; i < 32 && mySerial.available() > 0; ++i) {
        if (Serial.available() > 0) {
            break;
        }
        unsigned char value = static_cast<unsigned char>(mySerial.read());
        Serial.print('[');
        Serial.print(millis());
        Serial.print("] RX: ");
        print_hex_byte(value);
        Serial.println();
    }
}

void setup() {
    Serial.begin(115200);
    // Begin software serial communication on pins 10 (RX) and 11 (TX)
    mySerial.begin(9600);
    Serial.println("Ready. Type a command name and press Enter.");
    Serial.println("Controls: listen | listen on | listen off | listen toggle");
}

void loop() {
    handle_serial_input();
    read_chair_data();
    send_periodic();
}





////////////////////////////////////////////


// #include <Arduino.h>
// #include "SoftwareSerial.h"

// struct CommandDef {
//     const char *name;
//     uint8_t code;
// };

// static const CommandDef command_map[] = {
//     { "ramiona", 0x13 },
//     { "przedramiona", 0x12 },
//     { "nogi", 0x11 },
//     { "sila_nacisku_plus", 0x10 },
//     { "sila_nacisku_minus", 0x0F },
//     { "masaz_posladkow", 0x0E },
//     { "masaz_stop", 0x0D },
//     { "predkosc_masazu_stop", 0x02 },
//     { "pauza", 0x0B },
//     { "ogrzewanie", 0x03 },
//     { "czas", 0x07 },
//     { "masaz_calego_ciala", 0x04 },
//     { "grawitacja_zero", 0x08 },
//     { "tryb_automatyczny", 0x05 },
//     { "oparcie_w_gore", 0x09 },
//     { "oparcie_w_dol", 0x06 },
//     { "predkosc_minus", 0x14 },
//     { "predkosc_plus", 0x15 },
//     { "do_przodu_do_tylu_1", 0x16 },
//     { "plecy_i_talia", 0x17 },
//     { "do_przodu_do_tylu_2", 0x18 },
//     { "szyja", 0x19 },
//     { "power", 0x01 }
// };

// static const size_t COMMAND_COUNT = sizeof(command_map) / sizeof(command_map[0]);

// struct Scenario {
//     const char *name;
//     const uint8_t *seed_seq;
//     uint8_t seed_len;
// };

// struct WatchScenario {
//     const char *name;
//     const uint8_t *seed_seq;
//     uint8_t seed_len;
//     uint32_t observe_ms;
// };

// static const uint8_t SEED_BASELINE[] = {};
// static const uint8_t SEED_FULL_BODY[] = { 0x04 };
// static const uint8_t SEED_AUTO[] = { 0x05 };
// static const uint8_t SEED_ZERO_G[] = { 0x08 };
// static const uint8_t SEED_BACK_WAIST[] = { 0x17 };
// static const uint8_t SEED_NECK[] = { 0x19 };
// static const uint8_t SEED_FULL_BODY_PLUS[] = { 0x04, 0x10 };
// static const uint8_t SEED_FULL_BODY_SPEED[] = { 0x04, 0x15 };

// static const Scenario scenarios[] = {
//     { "baseline", SEED_BASELINE, 0 },
//     { "full_body", SEED_FULL_BODY, 1 },
//     { "auto", SEED_AUTO, 1 },
//     { "zero_gravity", SEED_ZERO_G, 1 },
//     { "back_waist", SEED_BACK_WAIST, 1 },
//     { "neck", SEED_NECK, 1 },
//     { "full_body_plus_intensity", SEED_FULL_BODY_PLUS, 2 },
//     { "full_body_plus_speed", SEED_FULL_BODY_SPEED, 2 }
// };

// static const size_t SCENARIO_COUNT = sizeof(scenarios) / sizeof(scenarios[0]);

// static const WatchScenario watch_scenarios[] = {
//     { "watch_baseline", SEED_BASELINE, 0, 70000UL },
//     { "watch_full_body", SEED_FULL_BODY, 1, 70000UL },
//     { "watch_auto", SEED_AUTO, 1, 70000UL }
// };

// static const size_t WATCH_COUNT = sizeof(watch_scenarios) / sizeof(watch_scenarios[0]);

// // -----------------------------------------------------------------------------
// // Settings
// // -----------------------------------------------------------------------------
// static const uint32_t USB_BAUD = 115200;
// static const uint32_t CHAIR_BAUD = 9600;
// static const uint32_t POLL_INTERVAL_MS = 100;

// // Send the same byte for several polls to emulate a held button.
// static const uint8_t PRESS_REPEAT = 6;

// // Stable frame detection
// static const uint8_t STABLE_FRAMES_REQUIRED = 3;

// // Timeouts and delays
// static const uint32_t STABLE_TIMEOUT_MS = 3000;
// static const uint32_t POWER_OFF_TIMEOUT_MS = 5000;
// static const uint32_t POWER_ON_TIMEOUT_MS = 6000;
// static const uint32_t INTER_COMMAND_GAP_MS = 350;
// static const uint32_t INTER_SEED_GAP_MS = 1000;
// static const uint32_t OFF_TO_ON_GAP_MS = 1500;
// static const uint32_t STARTUP_BASELINE_TIMEOUT_MS = 5000;

// // Safety / behavior
// static const bool RUN_MATRIX = true;
// static const bool RUN_TIME_WATCHERS = true;
// static const bool INCLUDE_POWER_IN_TESTS = false;
// static const bool INCLUDE_MOTION_COMMANDS = true;
// static const bool VERBOSE_ALL_FRAMES = false;

// // -----------------------------------------------------------------------------
// // UART / parser state
// // -----------------------------------------------------------------------------
// static SoftwareSerial mySerial(10, 11);

// static uint8_t active_command = 0x00;
// static uint8_t repeat_remaining = 0;
// static uint32_t last_send_ms = 0;

// static uint8_t parser_buf[7];
// static uint8_t parser_idx = 0;

// static uint8_t stable_candidate[7];
// static bool stable_candidate_valid = false;
// static uint8_t stable_count = 0;

// static uint8_t last_seen_frame[7];
// static bool last_seen_valid = false;

// // -----------------------------------------------------------------------------
// // Helpers
// // -----------------------------------------------------------------------------
// static void print_hex_byte(uint8_t v) {
//     Serial.print(F("0x"));
//     if (v < 0x10) Serial.print('0');
//     Serial.print(v, HEX);
// }

// static void print_frame(const uint8_t *f) {
//     for (int i = 0; i < 7; ++i) {
//         if (i) Serial.print(' ');
//         print_hex_byte(f[i]);
//     }
// }

// static bool frame_equals(const uint8_t *a, const uint8_t *b) {
//     for (int i = 0; i < 7; ++i) {
//         if (a[i] != b[i]) return false;
//     }
//     return true;
// }

// static void copy_frame(uint8_t *dst, const uint8_t *src) {
//     for (int i = 0; i < 7; ++i) dst[i] = src[i];
// }

// static void print_delta(const uint8_t *before, const uint8_t *after) {
//     bool any = false;
//     for (int i = 0; i < 7; ++i) {
//         if (before[i] != after[i]) {
//             if (any) Serial.print(',');
//             Serial.print(F("b"));
//             Serial.print(i);
//             Serial.print('=');
//             print_hex_byte(before[i]);
//             Serial.print(F("->"));
//             print_hex_byte(after[i]);
//             any = true;
//         }
//     }
//     if (!any) {
//         Serial.print(F("none"));
//     }
// }

// static const char* command_name(uint8_t code) {
//     for (size_t i = 0; i < COMMAND_COUNT; ++i) {
//         if (command_map[i].code == code) return command_map[i].name;
//     }
//     return "unknown";
// }

// static bool is_motion_command(uint8_t code) {
//     return (code == 0x06 || code == 0x09 || code == 0x16 || code == 0x18);
// }

// static bool should_test_command(uint8_t code) {
//     if (!INCLUDE_POWER_IN_TESTS && code == 0x01) return false;
//     if (!INCLUDE_MOTION_COMMANDS && is_motion_command(code)) return false;
//     return true;
// }

// static bool is_off_like_frame(const uint8_t *f) {
//     // Best current observed off/transition shape:
//     // AA 55 08 00 00 00 00
//     return (f[0] == 0xAA &&
//             f[1] == 0x55 &&
//             f[2] == 0x08 &&
//             f[3] == 0x00 &&
//             f[4] == 0x00 &&
//             f[5] == 0x00 &&
//             f[6] == 0x00);
// }

// static bool is_on_like_frame(const uint8_t *f) {
//     return !is_off_like_frame(f);
// }

// // -----------------------------------------------------------------------------
// // Parser / stability
// // -----------------------------------------------------------------------------
// static void reset_stability() {
//     stable_candidate_valid = false;
//     stable_count = 0;
// }

// static bool feed_parser(uint8_t b, uint8_t *out_frame) {
//     if (parser_idx == 0) {
//         if (b == 0xAA) {
//             parser_buf[parser_idx++] = b;
//         }
//         return false;
//     }

//     if (parser_idx == 1) {
//         if (b == 0x55) {
//             parser_buf[parser_idx++] = b;
//         } else if (b == 0xAA) {
//             parser_buf[0] = 0xAA;
//             parser_idx = 1;
//         } else {
//             parser_idx = 0;
//         }
//         return false;
//     }

//     if (b == 0xAA) {
//         parser_buf[0] = 0xAA;
//         parser_idx = 1;
//         return false;
//     }

//     parser_buf[parser_idx++] = b;

//     if (parser_idx == 7) {
//         for (int i = 0; i < 7; ++i) out_frame[i] = parser_buf[i];
//         parser_idx = 0;
//         return true;
//     }

//     return false;
// }

// static void on_frame_parsed(const uint8_t *frame) {
//     if (VERBOSE_ALL_FRAMES) {
//         if (!last_seen_valid || !frame_equals(last_seen_frame, frame)) {
//             Serial.print('[');
//             Serial.print(millis());
//             Serial.print(F("] FRAME "));
//             print_frame(frame);
//             Serial.println();
//             copy_frame(last_seen_frame, frame);
//             last_seen_valid = true;
//         }
//     }

//     if (!stable_candidate_valid) {
//         copy_frame(stable_candidate, frame);
//         stable_candidate_valid = true;
//         stable_count = 1;
//         return;
//     }

//     if (frame_equals(stable_candidate, frame)) {
//         if (stable_count < 255) stable_count++;
//     } else {
//         copy_frame(stable_candidate, frame);
//         stable_count = 1;
//     }
// }

// // -----------------------------------------------------------------------------
// // IO service
// // -----------------------------------------------------------------------------
// static void read_chair_data() {
//     uint8_t frame[7];
//     while (mySerial.available() > 0) {
//         uint8_t b = (uint8_t)mySerial.read();
//         if (feed_parser(b, frame)) {
//             on_frame_parsed(frame);
//         }
//     }
// }

// static void send_periodic() {
//     uint32_t now = millis();
//     if (now - last_send_ms < POLL_INTERVAL_MS) return;
//     last_send_ms = now;

//     uint8_t out = 0x00;
//     if (repeat_remaining > 0) {
//         out = active_command;
//         repeat_remaining--;
//     }
//     mySerial.write(out);
// }

// static void service_io() {
//     read_chair_data();
//     send_periodic();
// }

// static void quiet_gap(uint32_t ms) {
//     uint32_t start = millis();
//     while ((millis() - start) < ms) {
//         service_io();
//     }
// }

// // -----------------------------------------------------------------------------
// // Command actions
// // -----------------------------------------------------------------------------
// static void press_command(uint8_t code, uint8_t repeats = PRESS_REPEAT) {
//     active_command = code;
//     repeat_remaining = repeats;
// }

// static bool wait_for_stable_frame(uint8_t *out_frame, uint32_t timeout_ms) {
//     reset_stability();
//     uint32_t start = millis();

//     while ((millis() - start) < timeout_ms) {
//         service_io();
//         if (stable_candidate_valid && stable_count >= STABLE_FRAMES_REQUIRED) {
//             copy_frame(out_frame, stable_candidate);
//             return true;
//         }
//     }

//     if (stable_candidate_valid) {
//         copy_frame(out_frame, stable_candidate);
//     }
//     return false;
// }

// static bool wait_for_predicate_stable(bool (*pred)(const uint8_t *),
//                                       uint8_t *out_frame,
//                                       uint32_t timeout_ms) {
//     reset_stability();
//     uint32_t start = millis();

//     while ((millis() - start) < timeout_ms) {
//         service_io();
//         if (stable_candidate_valid &&
//             stable_count >= STABLE_FRAMES_REQUIRED &&
//             pred(stable_candidate)) {
//             copy_frame(out_frame, stable_candidate);
//             return true;
//         }
//     }

//     if (stable_candidate_valid) {
//         copy_frame(out_frame, stable_candidate);
//     }
//     return false;
// }

// static bool send_command_and_wait_stable(uint8_t code,
//                                          uint8_t *out_frame,
//                                          uint32_t timeout_ms = STABLE_TIMEOUT_MS) {
//     press_command(code, PRESS_REPEAT);

//     reset_stability();
//     uint32_t start = millis();

//     while ((millis() - start) < timeout_ms) {
//         service_io();
//         if (repeat_remaining == 0 &&
//             stable_candidate_valid &&
//             stable_count >= STABLE_FRAMES_REQUIRED) {
//             copy_frame(out_frame, stable_candidate);
//             return true;
//         }
//     }

//     if (stable_candidate_valid) {
//         copy_frame(out_frame, stable_candidate);
//     }
//     return false;
// }

// // -----------------------------------------------------------------------------
// // Clean reset sequence
// // -----------------------------------------------------------------------------
// static bool force_clean_on_state(uint8_t *out_frame) {
//     uint8_t cur[7];
//     bool have_cur = wait_for_stable_frame(cur, STARTUP_BASELINE_TIMEOUT_MS);

//     Serial.print(F("RESET|initial_stable="));
//     Serial.print(have_cur ? F("yes") : F("no"));
//     Serial.print(F("|frame="));
//     if (have_cur) print_frame(cur);
//     else Serial.print(F("n/a"));
//     Serial.println();

//     if (have_cur && is_on_like_frame(cur)) {
//         uint8_t off_frame[7];
//         Serial.println(F("RESET|action=power_off"));
//         bool got_off = send_command_and_wait_stable(0x01, off_frame, POWER_OFF_TIMEOUT_MS);
//         Serial.print(F("RESET|off_stable="));
//         Serial.print(got_off ? F("yes") : F("no"));
//         Serial.print(F("|frame="));
//         if (got_off) print_frame(off_frame);
//         else Serial.print(F("n/a"));
//         Serial.println();
//         quiet_gap(OFF_TO_ON_GAP_MS);
//     } else {
//         Serial.println(F("RESET|action=already_off_or_unknown"));
//         quiet_gap(OFF_TO_ON_GAP_MS);
//     }

//     uint8_t on_frame[7];
//     Serial.println(F("RESET|action=power_on"));
//     bool got_on = send_command_and_wait_stable(0x01, on_frame, POWER_ON_TIMEOUT_MS);
//     Serial.print(F("RESET|on_stable="));
//     Serial.print(got_on ? F("yes") : F("no"));
//     Serial.print(F("|frame="));
//     if (got_on) print_frame(on_frame);
//     else Serial.print(F("n/a"));
//     Serial.println();

//     if (got_on) {
//         copy_frame(out_frame, on_frame);
//     }
//     quiet_gap(INTER_COMMAND_GAP_MS);
//     return got_on;
// }

// // -----------------------------------------------------------------------------
// // Seed application
// // -----------------------------------------------------------------------------
// static bool apply_seed_sequence(const Scenario &sc, uint8_t *seeded_frame) {
//     if (sc.seed_len == 0) {
//         return wait_for_stable_frame(seeded_frame, STABLE_TIMEOUT_MS);
//     }

//     uint8_t tmp[7];
//     bool got = false;

//     for (uint8_t i = 0; i < sc.seed_len; ++i) {
//         const uint8_t code = sc.seed_seq[i];
//         got = send_command_and_wait_stable(code, tmp, STABLE_TIMEOUT_MS);

//         Serial.print(F("SEED|scenario="));
//         Serial.print(sc.name);
//         Serial.print(F("|step="));
//         Serial.print(i + 1);
//         Serial.print('/');
//         Serial.print(sc.seed_len);
//         Serial.print(F("|cmd="));
//         Serial.print(command_name(code));
//         Serial.print(F("|code="));
//         print_hex_byte(code);
//         Serial.print(F("|stable="));
//         Serial.print(got ? F("yes") : F("no"));
//         Serial.print(F("|frame="));
//         if (got) print_frame(tmp);
//         else Serial.print(F("n/a"));
//         Serial.println();

//         quiet_gap(INTER_SEED_GAP_MS);
//     }

//     got = wait_for_stable_frame(seeded_frame, STABLE_TIMEOUT_MS);
//     return got;
// }

// // -----------------------------------------------------------------------------
// // Matrix runner
// // -----------------------------------------------------------------------------
// static void log_result(const char *scenario_name,
//                        const char *cmd_name,
//                        uint8_t cmd_code,
//                        bool got_before,
//                        bool got_after,
//                        const uint8_t *before,
//                        const uint8_t *after) {
//     Serial.print(F("RESULT|scenario="));
//     Serial.print(scenario_name);
//     Serial.print(F("|cmd="));
//     Serial.print(cmd_name);
//     Serial.print(F("|code="));
//     print_hex_byte(cmd_code);
//     Serial.print(F("|before_stable="));
//     Serial.print(got_before ? F("yes") : F("no"));
//     Serial.print(F("|after_stable="));
//     Serial.print(got_after ? F("yes") : F("no"));
//     Serial.print(F("|changed="));

//     bool changed = false;
//     if (got_before && got_after) {
//         changed = !frame_equals(before, after);
//     }
//     Serial.print(changed ? F("yes") : F("no"));

//     Serial.print(F("|before="));
//     if (got_before) print_frame(before);
//     else Serial.print(F("n/a"));

//     Serial.print(F("|after="));
//     if (got_after) print_frame(after);
//     else Serial.print(F("n/a"));

//     Serial.print(F("|delta="));
//     if (got_before && got_after) print_delta(before, after);
//     else Serial.print(F("n/a"));

//     Serial.println();
// }

// static void run_matrix() {
//     for (size_t s = 0; s < SCENARIO_COUNT; ++s) {
//         const Scenario &sc = scenarios[s];

//         Serial.println();
//         Serial.println(F("============================================================"));
//         Serial.print(F("SCENARIO_BEGIN|name="));
//         Serial.println(sc.name);
//         Serial.println(F("============================================================"));

//         for (size_t c = 0; c < COMMAND_COUNT; ++c) {
//             const CommandDef &cmd = command_map[c];
//             if (!should_test_command(cmd.code)) continue;

//             Serial.println();
//             Serial.print(F("TEST_BEGIN|scenario="));
//             Serial.print(sc.name);
//             Serial.print(F("|cmd="));
//             Serial.print(cmd.name);
//             Serial.print(F("|code="));
//             print_hex_byte(cmd.code);
//             Serial.println();

//             uint8_t clean_on[7];
//             bool got_clean = force_clean_on_state(clean_on);

//             uint8_t before[7];
//             bool got_before = false;

//             if (got_clean) {
//                 got_before = apply_seed_sequence(sc, before);
//             }

//             Serial.print(F("PRESTATE|scenario="));
//             Serial.print(sc.name);
//             Serial.print(F("|cmd="));
//             Serial.print(cmd.name);
//             Serial.print(F("|stable="));
//             Serial.print(got_before ? F("yes") : F("no"));
//             Serial.print(F("|frame="));
//             if (got_before) print_frame(before);
//             else Serial.print(F("n/a"));
//             Serial.println();

//             uint8_t after[7];
//             bool got_after = false;

//             if (got_before) {
//                 got_after = send_command_and_wait_stable(cmd.code, after, STABLE_TIMEOUT_MS);
//             }

//             log_result(sc.name, cmd.name, cmd.code, got_before, got_after, before, after);

//             quiet_gap(INTER_COMMAND_GAP_MS);
//         }

//         Serial.print(F("SCENARIO_DONE|name="));
//         Serial.println(sc.name);
//     }

//     Serial.println();
//     Serial.println(F("MATRIX_DONE"));
// }

// // -----------------------------------------------------------------------------
// // Time watcher
// // -----------------------------------------------------------------------------
// static bool apply_watch_seed(const WatchScenario &ws, uint8_t *out_frame) {
//     Scenario temp = { ws.name, ws.seed_seq, ws.seed_len };
//     return apply_seed_sequence(temp, out_frame);
// }

// static void run_one_time_watch(const WatchScenario &ws) {
//     Serial.println();
//     Serial.println(F("------------------------------------------------------------"));
//     Serial.print(F("WATCH_BEGIN|name="));
//     Serial.print(ws.name);
//     Serial.print(F("|observe_ms="));
//     Serial.println(ws.observe_ms);
//     Serial.println(F("------------------------------------------------------------"));

//     uint8_t clean_on[7];
//     bool got_clean = force_clean_on_state(clean_on);

//     uint8_t start_frame[7];
//     bool got_start = false;

//     if (got_clean) {
//         got_start = apply_watch_seed(ws, start_frame);
//     }

//     Serial.print(F("WATCH_START|name="));
//     Serial.print(ws.name);
//     Serial.print(F("|stable="));
//     Serial.print(got_start ? F("yes") : F("no"));
//     Serial.print(F("|frame="));
//     if (got_start) print_frame(start_frame);
//     else Serial.print(F("n/a"));
//     Serial.println();

//     if (!got_start) {
//         Serial.print(F("WATCH_DONE|name="));
//         Serial.println(ws.name);
//         return;
//     }

//     uint8_t last_reported[7];
//     copy_frame(last_reported, start_frame);

//     uint32_t watch_start_ms = millis();

//     while ((millis() - watch_start_ms) < ws.observe_ms) {
//         uint8_t cur[7];
//         bool got = wait_for_stable_frame(cur, 1500);

//         if (got && !frame_equals(cur, last_reported)) {
//             Serial.print(F("WATCH_CHANGE|name="));
//             Serial.print(ws.name);
//             Serial.print(F("|t_ms="));
//             Serial.print(millis() - watch_start_ms);
//             Serial.print(F("|before="));
//             print_frame(last_reported);
//             Serial.print(F("|after="));
//             print_frame(cur);
//             Serial.print(F("|delta="));
//             print_delta(last_reported, cur);
//             Serial.println();
//             copy_frame(last_reported, cur);
//         }
//     }

//     Serial.print(F("WATCH_DONE|name="));
//     Serial.println(ws.name);
// }

// static void run_time_watchers() {
//     for (size_t i = 0; i < WATCH_COUNT; ++i) {
//         run_one_time_watch(watch_scenarios[i]);
//     }
//     Serial.println();
//     Serial.println(F("WATCHERS_DONE"));
// }

// // -----------------------------------------------------------------------------
// // Arduino entry points
// // -----------------------------------------------------------------------------
// void setup() {
//     Serial.begin(USB_BAUD);
//     mySerial.begin(CHAIR_BAUD);

//     Serial.println();
//     Serial.println(F("Massage chair clean-state matrix fuzzer"));
//     Serial.println(F("---------------------------------------"));
//     Serial.print(F("USB baud: "));
//     Serial.println(USB_BAUD);
//     Serial.print(F("Chair baud: "));
//     Serial.println(CHAIR_BAUD);
//     Serial.print(F("Poll interval ms: "));
//     Serial.println(POLL_INTERVAL_MS);
//     Serial.print(F("Press repeat: "));
//     Serial.println(PRESS_REPEAT);
//     Serial.print(F("Stable frames required: "));
//     Serial.println(STABLE_FRAMES_REQUIRED);
//     Serial.print(F("Include power in tests: "));
//     Serial.println(INCLUDE_POWER_IN_TESTS ? F("yes") : F("no"));
//     Serial.print(F("Include motion commands: "));
//     Serial.println(INCLUDE_MOTION_COMMANDS ? F("yes") : F("no"));
//     Serial.println();
// }

// void loop() {
//     static bool has_run = false;

//     if (!has_run) {
//         has_run = true;

//         if (RUN_MATRIX) {
//             run_matrix();
//         }

//         if (RUN_TIME_WATCHERS) {
//             run_time_watchers();
//         }

//         Serial.println(F("ALL_DONE"));
//     }

//     service_io();
// }