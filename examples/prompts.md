# Example Prompts

Real prompts tested with the pipeline. Each generates a complete BOM, PCB, CAD enclosure, assembly guide, and quote.

## Autonomous Drone
```
autonomous drone with GPS, altitude hold, and FPV camera
```
- **Opus result**: 38 parts, 71 PCB connections, 4-layer board, $377.48
- **Agents**: 6 stages, ~490s total
- **See**: `drone-build.json`

## Weather Station
```
IoT weather station with temperature, humidity, barometric pressure, and wind speed sensors
```
- **Expected**: ~20 parts, 2-layer PCB, ~$120

## Smart Home Controller
```
smart home hub with relay control for 4 appliances, WiFi, and OLED display
```
- **Expected**: ~15 parts, 2-layer PCB, ~$60

## Robot Arm
```
3-axis robotic arm with servo motors and joystick control
```
- **Expected**: ~18 parts, 2-layer PCB, ~$90

## LED Matrix Display
```
8x32 LED matrix scrolling text display with WiFi and web configuration
```
- **Expected**: ~12 parts, 2-layer PCB, ~$40
