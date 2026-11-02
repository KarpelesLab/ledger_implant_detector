# RF session 2026-11-02: S11 of the implant antennas themselves (Nano X, Flex)

- Instrument: NanoVNA-F V2 (SYSJOINT), fw 0.6.0 (build Jun 18 2025), SN 4A3639384505514B
- Capture: `tools/nanovna_capture.py`, 50 MHz - 3 GHz, 401 points (2 interleaved 201-pt scans), 4x averaged, S11.
- Calibration: SOL at the end of a ~10 cm SMA extension cable on port 1 (keeps the wallet away from the
  VNA), 50 MHz - 3 GHz, 201 points, saved to slot 0 (replaces the two-cable OSLT of 2026-10-26).
  Load check: <= -39 dB over the span (`load_check.s1p`).
- Adapter: a solid MHF4-to-SMA adapter on the extension cable. Open-ended (`adapter_open.s1p`): 7.6 ps
  round trip, |S11| within +-0.1 dB of 0 dB, so it is used without de-embedding (< 1 deg at 3 GHz).
  The implant's coax ends in an **MHF4** plug, not u.FL (a u.FL adapter tried on 2026-10-27 did not fit).
- DUT: the real implant's antenna (FPC "AC-A2016-NANO-V1.1" glued in the pink back shell) through its own
  micro-coax, MHF4 plug unplugged from the modem and onto the adapter. Nothing powered. Wallet on a
  non-metal surface, hands >= 10 cm away. "Boards" = the Ledger main board and the implant modem board.

## Captures (in order)

| file | state |
|---|---|
| `ant_installed_1`, `_2` | as found: battery and both boards in place (case held slightly open by the coax) |
| `ant_shell_only_1` | antenna in the shell only: battery out, both boards > 10 cm away |
| `ant_batt_noboards_1` | battery back in, no boards |
| `ant_boards_nobatt_1` | both boards back in, battery out |
| `ant_reassembled_1` | everything back in (battery + boards), same coax routing |

`_1` and `_2` of the installed state agree to < 0.01 in |S11| (max 0.44 dB, only at the -17 dB null).

## Results: S11 minima per band

| state | LTE low 699-960 | 1.05-1.3 GHz | LTE mid 1710-2200 | 2.3-3 GHz |
|---|---|---|---|---|
| installed | -5.4 dB @ 802 | **-7.5 dB @ 1156** | -5.3 dB @ 2115 | -14.7 @ 2558, -17.6 @ 2867 |
| shell only | -3.5 dB @ 883 | **-23.7 dB @ 1245** (56.6+2j ohm) | -18.9 dB @ 2115 | -14.0 @ 2307 |
| + battery, no boards | -1.3 dB @ 876 | -10.2 dB @ 1237 | -16.9 dB @ 2196 | -18.7 @ 2351 |
| + boards, no battery | -4.9 dB @ 876 | -8.7 dB @ 1105 | -8.9 dB @ 2196 | -13.0 @ 2440 |
| reassembled | -5.7 dB @ 957 | **-7.1 dB @ 1178** | -5.2 dB @ 2115 | -24.6 @ 2528 |

## What this says

1. **The implant antenna has its own resonance at 1.1-1.25 GHz**: very well matched on its own in the
   shell (-23.7 dB at 1245 MHz), 1156 MHz as found, 1178 MHz after reassembly. This is what the TEM cell
   sees as its notch at 1171 MHz (2026-10-26, unit closed, coax on the modem): the antenna system itself,
   not a fixture artefact.
2. **Free of the wallet, the antenna looks designed for LTE mid** (band 1, -18.9 dB at 2115 MHz, better
   than -10 dB from ~1.95 to ~2.45 GHz). It has no LTE low match of its own.
3. **The boards do the detuning.** On their own they pull the 1.2 GHz resonance down by 140 MHz
   (1245 -> 1105 MHz), create the LTE low match and halve the LTE mid match, presumably through their
   ground (the modem board tied to the Ledger's). The battery alone barely shifts anything but damps the
   1.2 GHz resonance (-24 -> -10 dB). With the boards in, adding the battery moves the resonance back up
   ~50 MHz (1105 -> 1156) and the LTE low match down (876 -> 802): the effects do not add.
4. **The installed state is not exactly reproducible after disassembly.** Reassembled, the LTE low match
   moved 802 -> 957 MHz and the 2.5-3 GHz part changed a lot; the 1.2 GHz resonance moved only
   +22 MHz with the same depth, and LTE mid stayed within 0.1 dB. Likely cause (user): the case cannot be
   fully closed with the coax routed out, so the boards sit at a slightly different distance from the
   antenna. Visual inspection of the micro-coax and plug showed no damage; the pattern (1.2 GHz and LTE
   mid stable, board-sensitive parts moved) also points to geometry rather than a damaged cable.
5. For the detector: the 1.05-1.3 GHz resonance is the most robust feature of this implant, but its exact
   frequency depends on the implant's ground and how it sits against the boards. Look for a narrow
   absorption feature in that range that a genuine reference lacks, not a fixed frequency.

## Ledger Flex implant (same calibration and adapter)

The Flex implant's antenna is a different, much larger FPC than the Nano X one (user); its coax also ends
in an MHF4 plug. Unlike the Nano X, the Flex battery is not on the back shell, so the antenna sits free.

| file | state |
|---|---|
| `flex_ant_installed_1`, `_2` | as found (case closed as far as the coax allows); repeat < 0.26 dB below 2.7 GHz |
| `flex_ant_shell_only_1` | antenna in the plastic shell only |
| `flex_ant_reassembled_1` | reassembled after that |

| state | LTE low 699-960 | 1.05-1.4 GHz | LTE mid 1710-2200 | 2.3-3 GHz |
|---|---|---|---|---|
| installed | **-8.5 dB @ 751** (-3 dB from ~600 to 1030 MHz) | **-8.4 dB @ 1304** | -12.9 dB @ 2056 | -14.8 @ 2683, -27 @ 2852, -31 @ 3000 |
| shell only | -6.1 dB @ 765 | -7.2 dB @ 1296 | -4.9 dB @ 2063 | ~ -4 dB throughout |
| reassembled | -7.7 dB @ 758 | -8.2 dB @ 1326 | -15.8 dB @ 2056 | -8.5 @ 2683, -12.3 @ 2904 |

- **The Flex antenna's narrow resonance is at ~1.3 GHz and belongs to the antenna alone**: 1296 MHz in the
  bare shell, 1304 / 1326 MHz installed / reassembled. The Flex's internals barely move it (the Nano X
  boards moved the same kind of resonance by 140 MHz). In the TEM cell its notch should sit near 1.3 GHz,
  still inside the cell's clean range (<= ~1.5 GHz).
- On its own it is a poor antenna (~ -4 dB across LTE mid / high); it only matches well assembled, so it
  appears to use the Flex's internals as its counterpoise. The Nano X antenna was the reverse.
- Reassembly moved LTE low by +7 MHz and the 1.3 GHz resonance by +22 MHz, kept LTE mid's frequency;
  as with the Nano X, the region above ~2.5 GHz changed most (up to 6.6 dB at deep nulls).

Open: re-measure the closed unit (coax back on the modem) in the TEM cell to see whether the notch moved
with the reassembly; that needs the two-cable OSLT calibration again.
