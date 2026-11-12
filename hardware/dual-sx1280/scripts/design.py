"""Single source of truth for the dual-SX1280 (2x NiceRF LoRa1280) board.

Both the schematic generator (gen_sch.py) and the PCB generator (gen_pcb.py)
import this file, so the schematic netlist and the PCB nets can never drift.

Coordinates for the PCB are in mm, board top-left = (0, 0), x right, y down,
seen from the TOP side. Parts with side="B" are mounted on the bottom.
"""

BOARD_W = 20.0   # mm
BOARD_H = 33.0   # mm
PCB_ORIGIN = (100.0, 100.0)  # where (0,0) of the board lands on the KiCad sheet

PROJECT = "dual_sx1280"

# ---------------------------------------------------------------------------
# Parts: ref -> dict(symbol, footprint, value, pos=(x,y), rot, side, extra)
#   symbol    : "lib:name" as used in the schematic (project lib = "dual_sx1280")
#   footprint : "lib:name" (project fp lib = "dual_sx1280")
#   lcsc      : LCSC part number hint for JLCPCB assembly (verify stock!)
# ---------------------------------------------------------------------------
PARTS = {
    # --- Radios -------------------------------------------------------------
    "U1": dict(symbol="dual_sx1280:LoRa1280", footprint="dual_sx1280:NiceRF_LoRa1280_16x16mm",
               value="LoRa1280 (radio A)", pos=(10.0, 9.5), rot=0, side="F",
               mpn="NiceRF LoRa1280", lcsc="", dnp_asm=True),
    "U2": dict(symbol="dual_sx1280:LoRa1280", footprint="dual_sx1280:NiceRF_LoRa1280_16x16mm",
               value="LoRa1280 (radio B)", pos=(10.0, 9.5), rot=0, side="B",
               mpn="NiceRF LoRa1280", lcsc="", dnp_asm=True),
    # --- MCU ------------------------------------------------------------------
    "U3": dict(symbol="MCU_ST_STM32F1:STM32F103CBUx",
               footprint="Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.6x5.6mm",
               value="STM32F103CBU6", pos=(8.0, 25.0), rot=0, side="F",
               mpn="STM32F103CBU6", lcsc=""),
    # --- Power ----------------------------------------------------------------
    "U4": dict(symbol="dual_sx1280:AP2112K-3.3", footprint="Package_TO_SOT_SMD:SOT-23-5",
               value="AP2112K-3.3", pos=(16.8, 27.0), rot=90, side="F",
               mpn="AP2112K-3.3TRG1", lcsc="C51118"),
    "C1": dict(symbol="Device:C", footprint="Capacitor_SMD:C_0402_1005Metric", value="1u",
               pos=(18.8, 30.4), rot=0, side="F", mpn="CL05A105KA5NQNC", lcsc="C52923"),
    "C2": dict(symbol="Device:C", footprint="Capacitor_SMD:C_0603_1608Metric", value="10u",
               pos=(15.6, 30.6), rot=0, side="F", mpn="CL10A106KP8NNNC", lcsc="C19702"),
    # --- MCU support ------------------------------------------------------------
    "C3": dict(symbol="Device:C", footprint="Capacitor_SMD:C_0402_1005Metric", value="100n",
               pos=(12.9, 21.2), rot=90, side="F", mpn="CL05B104KO5NNNC", lcsc="C1525"),
    "C4": dict(symbol="Device:C", footprint="Capacitor_SMD:C_0402_1005Metric", value="100n",
               pos=(12.9, 28.6), rot=90, side="F", mpn="CL05B104KO5NNNC", lcsc="C1525"),
    "C5": dict(symbol="Device:C", footprint="Capacitor_SMD:C_0402_1005Metric", value="100n",
               pos=(3.0, 20.3), rot=0, side="F", mpn="CL05B104KO5NNNC", lcsc="C1525"),
    "C6": dict(symbol="Device:C", footprint="Capacitor_SMD:C_0402_1005Metric", value="100n",
               pos=(2.0, 25.6), rot=90, side="F", mpn="CL05B104KO5NNNC", lcsc="C1525"),
    "C7": dict(symbol="Device:C", footprint="Capacitor_SMD:C_0402_1005Metric", value="1u",
               pos=(2.0, 27.6), rot=90, side="F", mpn="CL05A105KA5NQNC", lcsc="C52923"),
    "C8": dict(symbol="Device:C", footprint="Capacitor_SMD:C_0402_1005Metric", value="100n",
               pos=(2.0, 23.4), rot=90, side="F", mpn="CL05B104KO5NNNC", lcsc="C1525"),
    "R1": dict(symbol="Device:R", footprint="Resistor_SMD:R_0402_1005Metric", value="10k",
               pos=(5.2, 30.6), rot=0, side="F", mpn="0402WGF1002TCE", lcsc="C25744"),
    # --- Status LEDs ------------------------------------------------------------
    "D1": dict(symbol="Device:LED", footprint="LED_SMD:LED_0402_1005Metric", value="GRN (radio A)",
               pos=(15.4, 24.4), rot=0, side="B", mpn="0402 green LED", lcsc=""),
    "D2": dict(symbol="Device:LED", footprint="LED_SMD:LED_0402_1005Metric", value="BLU (radio B)",
               pos=(15.4, 26.8), rot=0, side="B", mpn="0402 blue LED", lcsc=""),
    "R2": dict(symbol="Device:R", footprint="Resistor_SMD:R_0402_1005Metric", value="1k",
               pos=(15.4, 23.2), rot=0, side="B", mpn="0402WGF1001TCE", lcsc="C11702"),
    "R3": dict(symbol="Device:R", footprint="Resistor_SMD:R_0402_1005Metric", value="1k",
               pos=(15.4, 25.6), rot=0, side="B", mpn="0402WGF1001TCE", lcsc="C11702"),
    # --- Radio A support (top) --------------------------------------------------
    "J1": dict(symbol="Connector:Conn_Coaxial", footprint="Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical",
               value="U.FL ANT-A", pos=(17.525, 20.0), rot=270, side="F", mpn="U.FL-R-SMT-1(10)", lcsc="C88374"),
    "C9": dict(symbol="Device:C", footprint="Capacitor_SMD:C_0603_1608Metric", value="10u",
               pos=(6.6, 18.7), rot=0, side="F", mpn="CL10A106KP8NNNC", lcsc="C19702"),
    "C10": dict(symbol="Device:C", footprint="Capacitor_SMD:C_0402_1005Metric", value="100n",
               pos=(2.0, 18.7), rot=0, side="F", mpn="CL05B104KO5NNNC", lcsc="C1525"),
    "JP1": dict(symbol="Jumper:SolderJumper_3_Bridged12",
                footprint="Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm",
                value="TCXO_A sel", pos=(17.0, 23.6), rot=0, side="F", mpn="", lcsc=""),
    # --- Radio B support (bottom) -----------------------------------------------
    "J2": dict(symbol="Connector:Conn_Coaxial", footprint="Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical",
               value="U.FL ANT-B", pos=(2.475, 20.0), rot=270, side="B", mpn="U.FL-R-SMT-1(10)", lcsc="C88374"),
    "C11": dict(symbol="Device:C", footprint="Capacitor_SMD:C_0603_1608Metric", value="10u",
                pos=(12.9, 19.0), rot=0, side="B", mpn="CL10A106KP8NNNC", lcsc="C19702"),
    "C12": dict(symbol="Device:C", footprint="Capacitor_SMD:C_0402_1005Metric", value="100n",
                pos=(15.4, 19.0), rot=0, side="B", mpn="CL05B104KO5NNNC", lcsc="C1525"),
    "JP2": dict(symbol="Jumper:SolderJumper_3_Bridged12",
                footprint="Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm",
                value="TCXO_B sel", pos=(8.0, 19.3), rot=0, side="B", mpn="", lcsc=""),
    # --- Host connector + programming pads (bottom) ------------------------------
    "J3": dict(symbol="Connector_Generic_MountingPin:Conn_01x04_MountingPin",
               footprint="Connector_JST:JST_SH_SM04B-SRSS-TB_1x04-1MP_P1.00mm_Horizontal",
               value="UART/5V JST-SH", pos=(10.0, 29.8), rot=0, side="B",
               mpn="SM04B-SRSS-TB(LF)(SN)", lcsc="C160404"),
    "TP1": dict(symbol="Connector:TestPoint", footprint="TestPoint:TestPoint_Pad_D1.0mm",
                value="SWDIO", pos=(2.0, 24.0), rot=0, side="B", mpn="", lcsc=""),
    "TP2": dict(symbol="Connector:TestPoint", footprint="TestPoint:TestPoint_Pad_D1.0mm",
                value="SWCLK", pos=(2.0, 26.0), rot=0, side="B", mpn="", lcsc=""),
    "TP3": dict(symbol="Connector:TestPoint", footprint="TestPoint:TestPoint_Pad_D1.0mm",
                value="NRST", pos=(2.0, 28.0), rot=0, side="B", mpn="", lcsc=""),
    "TP4": dict(symbol="Connector:TestPoint", footprint="TestPoint:TestPoint_Pad_D1.0mm",
                value="3V3", pos=(18.0, 24.0), rot=0, side="B", mpn="", lcsc=""),
    "TP5": dict(symbol="Connector:TestPoint", footprint="TestPoint:TestPoint_Pad_D1.0mm",
                value="GND", pos=(18.0, 26.0), rot=0, side="B", mpn="", lcsc=""),
    "TP6": dict(symbol="Connector:TestPoint", footprint="TestPoint:TestPoint_Pad_D1.0mm",
                value="BOOT0", pos=(18.0, 28.0), rot=0, side="B", mpn="", lcsc=""),
}

# ---------------------------------------------------------------------------
# Nets: name -> list of "REF.PIN"
# ---------------------------------------------------------------------------
NETS = {
    # power
    "+5V":   ["J3.1", "U4.1", "U4.3", "C1.1"],
    "+3V3":  ["U4.5", "C2.1",
              "U3.1", "U3.9", "U3.24", "U3.36", "U3.48",
              "C3.1", "C4.1", "C5.1", "C6.1", "C7.1",
              "U1.3", "C9.1", "C10.1", "JP1.3",
              "U2.3", "C11.1", "C12.1", "JP2.3",
              "TP4.1"],
    "GND":   ["J3.4", "J3.MP", "U4.2", "C1.2", "C2.2",
              "U3.8", "U3.23", "U3.35", "U3.47", "U3.49",
              "C3.2", "C4.2", "C5.2", "C6.2", "C7.2", "C8.2", "R1.2",
              "D1.1", "D2.1",
              "U1.4", "U1.10", "U1.11", "U1.12", "J1.2", "C9.2", "C10.2", "JP1.1",
              "U2.4", "U2.10", "U2.11", "U2.12", "J2.2", "C11.2", "C12.2", "JP2.1",
              "TP5.1"],
    # MCU housekeeping
    "NRST":    ["U3.7", "C8.1", "TP3.1"],
    "BOOT0":   ["U3.44", "R1.1", "TP6.1"],
    "SWDIO":   ["U3.34", "TP1.1"],
    "SWCLK":   ["U3.37", "TP2.1"],
    # host UART (USART1, also the STM32 ROM bootloader port)
    "UART_TX": ["U3.30", "J3.2"],   # PA9  -> host RX
    "UART_RX": ["U3.31", "J3.3"],   # PA10 <- host TX
    # LEDs
    "LED_A":   ["U3.45", "R2.1"],   # PB8
    "LED_A_K": ["R2.2", "D1.2"],
    "LED_B":   ["U3.46", "R3.1"],   # PB9
    "LED_B_K": ["R3.2", "D2.2"],
    # Radio A on SPI1
    "A_NSS":    ["U3.14", "U1.8"],   # PA4
    "A_SCK":    ["U3.15", "U1.7"],   # PA5 SPI1_SCK
    "A_MISO":   ["U3.16", "U1.5"],   # PA6 SPI1_MISO
    "A_MOSI":   ["U3.17", "U1.6"],   # PA7 SPI1_MOSI
    "A_BUSY":   ["U3.18", "U1.15"],  # PB0
    "A_DIO1":   ["U3.19", "U1.16"],  # PB1  (EXTI1)
    "A_NRESET": ["U3.11", "U1.13"],  # PA1
    "A_TCXO":   ["U1.14", "JP1.2"],
    "RF_A":     ["U1.9", "J1.1"],
    # Radio B on SPI2
    "B_NSS":    ["U3.25", "U2.8"],   # PB12
    "B_SCK":    ["U3.26", "U2.7"],   # PB13 SPI2_SCK
    "B_MISO":   ["U3.27", "U2.5"],   # PB14 SPI2_MISO
    "B_MOSI":   ["U3.28", "U2.6"],   # PB15 SPI2_MOSI
    "B_BUSY":   ["U3.21", "U2.15"],  # PB10
    "B_DIO1":   ["U3.29", "U2.16"],  # PA8  (EXTI8)
    "B_NRESET": ["U3.22", "U2.13"],  # PB11
    "B_TCXO":   ["U2.14", "JP2.2"],
    "RF_B":     ["U2.9", "J2.1"],
}

# Pins intentionally left unconnected (get a no-connect flag in the schematic)
NO_CONNECT = [
    "U1.1", "U1.2", "U2.1", "U2.2",             # DIO2/DIO3 unused (all IRQs routed to DIO1)
    "U3.2", "U3.3", "U3.4", "U3.5", "U3.6",     # PC13-15, PD0/PD1 (no crystal, HSI used)
    "U3.10", "U3.12", "U3.13",                  # PA0, PA2, PA3 spare
    "U3.20", "U3.32", "U3.33", "U3.38",         # PB2, PA11, PA12, PA15 spare
    "U3.39", "U3.40", "U3.41", "U3.42", "U3.43",  # PB3-PB7 spare
    "U4.4",                                     # AP2112 NC pin
]

POWER_NETS = {"+5V", "+3V3", "GND"}
RF_NETS = {"RF_A", "RF_B"}


def pin_to_net():
    m = {}
    for net, pins in NETS.items():
        for p in pins:
            assert p not in m, f"pin {p} on two nets: {m.get(p)} and {net}"
            m[p] = net
    for p in NO_CONNECT:
        assert p not in m, f"NC pin {p} is also on net {m[p]}"
    return m


if __name__ == "__main__":
    m = pin_to_net()
    print(f"{len(PARTS)} parts, {len(NETS)} nets, {len(m)} connected pins, {len(NO_CONNECT)} NC pins")
