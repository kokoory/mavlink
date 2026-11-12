/*
 * Dual SX1280 board (2x NiceRF LoRa1280) - STM32F103CBU6 pin map.
 * Mirrors hardware/dual-sx1280/scripts/design.py (the source of truth).
 *
 * Clock: no crystal fitted -> run from HSI (8 MHz, PLL up to 64 MHz).
 * Radio A = U1 (top side, U.FL J1), Radio B = U2 (bottom side, U.FL J2).
 * DIO2/DIO3 of both modules are not connected: map every IRQ to DIO1.
 */
#pragma once

/* ---- Radio A : SPI1 ---------------------------------------------------- */
#define RADIO_A_SPI            SPI1
#define RADIO_A_SCK_PORT       GPIOA
#define RADIO_A_SCK_PIN        5      /* PA5  SPI1_SCK  */
#define RADIO_A_MISO_PORT      GPIOA
#define RADIO_A_MISO_PIN       6      /* PA6  SPI1_MISO */
#define RADIO_A_MOSI_PORT      GPIOA
#define RADIO_A_MOSI_PIN       7      /* PA7  SPI1_MOSI */
#define RADIO_A_NSS_PORT       GPIOA
#define RADIO_A_NSS_PIN        4      /* PA4  GPIO (software NSS) */
#define RADIO_A_BUSY_PORT      GPIOB
#define RADIO_A_BUSY_PIN       0      /* PB0  input */
#define RADIO_A_DIO1_PORT      GPIOB
#define RADIO_A_DIO1_PIN       1      /* PB1  EXTI1 rising */
#define RADIO_A_NRESET_PORT    GPIOA
#define RADIO_A_NRESET_PIN     1      /* PA1  output, active low */

/* ---- Radio B : SPI2 ---------------------------------------------------- */
#define RADIO_B_SPI            SPI2
#define RADIO_B_SCK_PORT       GPIOB
#define RADIO_B_SCK_PIN        13     /* PB13 SPI2_SCK  */
#define RADIO_B_MISO_PORT      GPIOB
#define RADIO_B_MISO_PIN       14     /* PB14 SPI2_MISO */
#define RADIO_B_MOSI_PORT      GPIOB
#define RADIO_B_MOSI_PIN       15     /* PB15 SPI2_MOSI */
#define RADIO_B_NSS_PORT       GPIOB
#define RADIO_B_NSS_PIN        12     /* PB12 GPIO (software NSS) */
#define RADIO_B_BUSY_PORT      GPIOB
#define RADIO_B_BUSY_PIN       10     /* PB10 input */
#define RADIO_B_DIO1_PORT      GPIOA
#define RADIO_B_DIO1_PIN       8      /* PA8  EXTI8 rising (EXTI9_5 IRQ) */
#define RADIO_B_NRESET_PORT    GPIOB
#define RADIO_B_NRESET_PIN     11     /* PB11 output, active low */

/* ---- Host link (MAVLink / serial) : USART1, also ROM bootloader port ---- */
#define HOST_UART              USART1
#define HOST_TX_PORT           GPIOA
#define HOST_TX_PIN            9      /* PA9  -> J3 pin 2 */
#define HOST_RX_PORT           GPIOA
#define HOST_RX_PIN            10     /* PA10 <- J3 pin 3 */

/* ---- Status LEDs (active high, 1k series) ------------------------------- */
#define LED_A_PORT             GPIOB
#define LED_A_PIN              8      /* PB8  D1 green, bottom side */
#define LED_B_PORT             GPIOB
#define LED_B_PIN              9      /* PB9  D2 blue,  bottom side */

/* Spare, unconnected: PA0, PA2, PA3 (USART2), PA11, PA12, PA15, PB2, PB3-PB7, PC13-PC15 */
