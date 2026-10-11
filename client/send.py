#!/usr/bin/env python3
"""Send a chain proof to the TerraSol SP1 verifier program on Solana.

Builds one transaction: compute budget + one instruction to the verifier program with
proof (356 bytes) + public values (188 bytes). Then reads compute units and the log.

Usage:
  send.py --rpc URL --program PUBKEY --payer KEYPAIR.json --data DIR [--tamper]

--tamper changes the volume by 1 and skips preflight, so the rejection is visible on-chain.
The payer key is never printed. Use a throwaway devnet keypair.
"""
import argparse
import base64
import json
import time
import urllib.request

from solders.compute_budget import set_compute_unit_limit
from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction


def rpc(url, method, params):
    req = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        answer = json.loads(r.read())
    if "error" in answer:
        raise RuntimeError(f"{method}: {answer['error']}")
    return answer["result"]


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--rpc", required=True)
    a.add_argument("--program", required=True)
    a.add_argument("--payer", required=True)
    a.add_argument("--data", required=True)
    a.add_argument("--tamper", action="store_true")
    a.add_argument("--cu", type=int, default=400_000)
    x = a.parse_args()

    with open(x.payer) as f:
        payer = Keypair.from_bytes(bytes(json.load(f)))
    proof = open(f"{x.data}/chain_proof.bin", "rb").read()
    values = bytearray(open(f"{x.data}/chain_public_values.bin", "rb").read())
    assert len(proof) == 356 and len(values) == 188
    if x.tamper:
        values[180] ^= 1  # volume changed by 1

    ix = Instruction(Pubkey.from_string(x.program), bytes(proof) + bytes(values), [])
    blockhash = Hash.from_string(rpc(x.rpc, "getLatestBlockhash", [{"commitment": "confirmed"}])["value"]["blockhash"])
    msg = Message.new_with_blockhash([set_compute_unit_limit(x.cu), ix], payer.pubkey(), blockhash)
    tx = Transaction([payer], msg, blockhash)
    raw = bytes(tx)
    print(f"Transaction {len(raw)} bytes (limit 1232), volume {'TAMPERED' if x.tamper else 'original'}")

    sig = rpc(
        x.rpc,
        "sendTransaction",
        [base64.b64encode(raw).decode(), {"encoding": "base64", "skipPreflight": x.tamper, "preflightCommitment": "confirmed"}],
    )
    print(f"Signature: {sig}")
    for _ in range(60):
        st = rpc(x.rpc, "getSignatureStatuses", [[sig]])["value"][0]
        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
            break
        time.sleep(1)
    t = None
    for _ in range(30):
        t = rpc(x.rpc, "getTransaction", [sig, {"encoding": "json", "commitment": "confirmed", "maxSupportedTransactionVersion": 0}])
        if t:
            break
        time.sleep(1)
    meta = t["meta"]
    print(f"Slot {t['slot']}, fee {meta['fee']} lamports, compute units {meta.get('computeUnitsConsumed')}")
    print(f"Error: {meta['err']}")
    for line in meta.get("logMessages") or []:
        print("  " + line)


if __name__ == "__main__":
    main()
