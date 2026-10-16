# TerraSol SP1 Verifier for Solana

On-chain verification of **SP1 v6 Groth16 proofs** on Solana, using the `alt_bn128` syscalls.
One verification costs **104,874 compute units** (measured on devnet), well below the
default limit of 200,000 per instruction.

Built for **provable order matching**: an off-chain matching engine proves in SP1 that a chain
of blocks was processed by the matching rules, aggregates the block proofs into one 356-byte
Groth16 proof, and anyone can check it on Solana for a normal transaction fee.

| | |
|---|---|
| Proof | 356 bytes (SP1 Groth16, circuit v6.1.0, SP1 6.8.1) |
| Public values | 188 bytes (chain summary, see below) |
| Transaction | 754 bytes (limit 1,232) |
| Compute units | **104,874** (devnet, 0.1.0) · **104,884** (local validator, 0.2.0) · **104,874** (local validator, 0.2.1) |
| Fee | 5,000 lamports |
| Program size | 29 KB |

## Measured on devnet (10 Oct 2026)

Sample proof in `data/`: 10 blocks, 100,000 orders, 42,757 fills, one 356-byte aggregate proof
(block proofs and aggregation on one RTX 4090; aggregation into Groth16 41.6 s).

| Check | Result |
|---|---|
| Original proof | **valid**, 104,874 CU – [transaction](https://explorer.solana.com/tx/4URvjCLvyuiVCZ1nLgwdbZH9EfzjRE82gwD15zxPyjZLRrpnxEdok5MP2j6TW5pzjGSdFaUnK7KWh9T3h9kUgAh6?cluster=devnet) |
| Volume changed by 1 | **rejected** (error 5) – [transaction](https://explorer.solana.com/tx/jMchmDjsjQfmv9kHE5SDJX6wkRUm65sDjvKubz245L2UEfpHHMxvcRcLSsaUodUcK7cbWqWPGcAXYTAitPiWooC?cluster=devnet) |
| Program | [`BcULPTv4…ZN99`](https://explorer.solana.com/address/BcULPTv4kmSRrXUXrB2zc6wQWyXLAfPYE9efjbHZZN99?cluster=devnet) |

The devnet program was built from the pre-release 0.1.0 (same Groth16 check and same key,
German identifiers and log text). Version 0.2.0 was the translated source: on a local validator
(Agave 4.3) it verified the same proof with **104,884 CU** and rejected the tampered one with
error 5 – raw log in `data/2026-10-11_local-validator_v0.2.0.txt`.
Version 0.2.1 verifies the same proof on a local validator with **104,874 CU** and rejects the
tampered one with error 5 – raw log in `data/2026-10-16_local-validator_v0.2.1.txt`.
**0.1.0 and 0.2.0 do not check the block program** (see *Changes*); the devnet program will be
replaced by a build of 0.2.1 or later.

## Why it is cheap

- The SP1 Groth16 verifying key is **decompressed at build time** (`vkgen`) into the big-endian
  format of the Solana syscalls. No point decompression or big-integer library runs on-chain.
- The program only hashes the public values (SHA-256 syscall), negates point A and runs one
  pairing check through [`groth16-solana`](https://crates.io/crates/groth16-solana).

## Layout

**Proof (356 bytes)** – exactly `SP1ProofWithPublicValues::bytes()`:

| Bytes | Content |
|---|---|
| 0..4 | first 4 bytes of SHA-256 of the SP1 Groth16 verifying key |
| 4..36 | exit code (must be 0) |
| 36..68 | vk_root of the SP1 recursion (must match) |
| 68..100 | proof nonce |
| 100..356 | Groth16 proof A (64), B (128), C (64) |

**Public inputs of the pairing check:** program vkey hash, SHA-256 of the public values with the
top 3 bits cleared, exit code, vk_root, nonce.

**Chain summary (188 bytes, little-endian)** – public values of the deployed program:

| Bytes | Field |
|---|---|
| 0..32 | key of the SP1 program that proved each block (`vk.hash_u32()`, 8 × u32) – must equal `BLOCK_VKEY` |
| 32..64 | state commitment at the start of the chain |
| 64..96 | state commitment at the end of the chain |
| 96..100 | number of blocks (u32) |
| 100..132 | hash over all inputs |
| 132..164 | hash over all results |
| 164..172 | number of inputs (u64) |
| 172..180 | number of results (u64) |
| 180..188 | volume (u64) |

The chain program verifies the block proofs inside SP1 against the block key it is given and
commits that key. A valid chain proof is therefore only meaningful together with the block key:
the deployed program compares it with `BLOCK_VKEY` in `program/src/vk.rs` and refuses any other
block program (error 6).

On success the program logs the summary and emits start and end commitment as log data,
so an indexer can anchor the chain. Error codes: 1 length, 2 key prefix, 3 exit code,
4 vk_root, 5 proof, 6 block program not the pinned one.

## Use as a library

```toml
terrasol-sp1-verifier = { git = "https://github.com/archtum66-dev/terrasol-sp1-verifier", features = ["no-entrypoint"] }
```

```rust
use terrasol_sp1_verifier::verify_sp1_groth16;
// proof: 356 bytes, public_values: any length, vkey_hash: vk.bytes32() of your SP1 program
verify_sp1_groth16(&proof, &public_values, &vkey_hash)?;
```

`verify_sp1_groth16` works for **any SP1 6.8.x program**. For chain proofs use
`verify_chain_proof_for(&proof, &values, &chain_vkey_hash, &block_vkey)`: it also refuses chains
whose blocks were proved by another block program. The deployed program accepts only the
chain program `PROGRAM_VKEY_HASH` and the block program `BLOCK_VKEY` fixed in `program/src/vk.rs`.

## Build and test

```
# regenerate the key file for your SP1 programs (optional)
cd vkgen && cargo run --release -- 0x<chain program vkey hash> 0x<block program key, 32 bytes as committed> ../program/src/vk.rs

# native tests (8): valid proof, same result as Succinct's sp1-verifier, tampered data rejected,
# block program pinned, a valid proof refused for another block program
cd program && cargo test --release

# Solana program (Agave 4.3, platform-tools v1.57, SBPF v3)
cargo-build-sbf --arch v3

# send the sample proof (throwaway devnet keypair)
pip install -r client/requirements.txt
python3 client/send.py --rpc https://api.devnet.solana.com --program <ID> --payer <keypair.json> --data data
python3 client/send.py … --tamper
```

## Changes

**0.2.1 (16 Oct 2026) – security fix.** Up to 0.2.0 the deployed program checked only the
chain program. The chain program takes the block key as a private input, so a chain built from
proofs of *any* block program verified as valid. 0.2.1 pins the block program (`BLOCK_VKEY`,
error 6) and adds `verify_chain_proof_for`. Found in an internal review on 15 Oct 2026; no
mainnet deployment exists. The devnet program (0.1.0) has the same gap and will be replaced.

**0.2.0 (11 Oct 2026)** – first public version.

## Status

- **Not audited.** Do not use on mainnet before an independent security review.
- The program does not keep state yet: it checks a proof, it does not check that a chain
  continues the previous one. A stateful anchor (start of a chain = end of the last one) is the
  next step.
- Groth16 over BN254 is **not post-quantum secure**. The inner SP1 STARK proofs are hash-based;
  verifying them directly on Solana is future work.
- The matching engine and the SP1 programs that produce the proofs are proprietary and
  **not part of this repository**.

## License

Apache-2.0, see `LICENSE`. Copyright 2026 TerraSol.
