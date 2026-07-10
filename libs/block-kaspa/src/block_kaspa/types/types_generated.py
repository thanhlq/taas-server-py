"""
Generated from kaspa restapi spec: https://api.kaspa.org

(Equivalent to taas-server-js/packages/kaspa/src/types/types.gen.ts)

Notes
-----
- Every model is a ``msgspec.Struct`` via :class:`foundation.serialization.BaseModel`.
- Field names are kept EXACTLY as the wire/JSON keys (the OpenAPI spec mixes
  camelCase and snake_case), so structs decode real API responses as-is.
- TypeScript ``number`` maps to ``int | float`` (``Number``) to accept either
  integer or decimal JSON numbers without precision loss on large amounts.
- Optional (``?``) fields become ``... | None = None``; within each struct the
  required fields are declared first (msgspec requires defaults to come last).
"""

from __future__ import annotations

from typing import Literal

from foundation.serialization import BaseModel

# TypeScript `number` is float64; the API uses it for both integers and decimals.
Number = int | float


# ── Enumerations ──────────────────────────────────────────────────────────────
AcceptanceMode = Literal["accepted", "rejected"]
PreviousOutpointLookupMode = Literal["no", "light", "full"]


# ── Models ────────────────────────────────────────────────────────────────────
class AddressBalanceHistory(BaseModel):
    timestamp: Number
    amount: Number


class AddressName(BaseModel):
    address: str
    name: str


class AddressesActiveCountResponse(BaseModel):
    timestamp: Number
    dateTime: str
    count: Number


class AddressesActiveRequest(BaseModel):
    addresses: list[str] | None = None


class AddressesActiveResponse(BaseModel):
    address: str
    active: bool
    lastTxBlockTime: Number | None = None


class BalanceRequest(BaseModel):
    addresses: list[str] | None = None


class BalanceResponse(BaseModel):
    address: str | None = None
    balance: Number | None = None


class BalancesByAddressEntry(BaseModel):
    address: str | None = None
    balance: Number | None = None


class BlockModel(BaseModel):
    header: EndpointsGetBlocksBlockHeader
    verboseData: VerboseDataModel
    transactions: list[BlockTxModel] | None = None
    extra: ExtraModel | None = None


class BlockResponse(BaseModel):
    blockHashes: list[str] | None = None
    blocks: list[BlockModel] | None = None


class BlockRewardResponse(BaseModel):
    blockreward: Number | None = None


class BlockTxInputModel(BaseModel):
    previousOutpoint: BlockTxInputPreviousOutpointModel | None = None
    signatureScript: str | None = None
    sigOpCount: Number | None = None
    sequence: Number | None = None


class BlockTxInputPreviousOutpointModel(BaseModel):
    transactionId: str
    index: Number


class BlockTxModel(BaseModel):
    verboseData: BlockTxVerboseDataModel
    inputs: list[BlockTxInputModel] | None = None
    outputs: list[BlockTxOutputModel] | None = None
    subnetworkId: str | None = None
    payload: str | None = None
    lockTime: Number | None = None
    gas: Number | None = None
    mass: Number | None = None
    version: Number | None = None


class BlockTxOutputModel(BaseModel):
    amount: Number | None = None
    scriptPublicKey: BlockTxOutputScriptPublicKeyModel | None = None
    verboseData: BlockTxOutputVerboseDataModel | None = None


class BlockTxOutputScriptPublicKeyModel(BaseModel):
    scriptPublicKey: str | None = None
    version: Number | None = None


class BlockTxOutputVerboseDataModel(BaseModel):
    scriptPublicKeyType: str | None = None
    scriptPublicKeyAddress: str | None = None


class BlockTxVerboseDataModel(BaseModel):
    transactionId: str
    hash: str | None = None
    computeMass: Number | None = None
    blockHash: str | None = None
    blockTime: Number | None = None


class BlockdagResponse(BaseModel):
    networkName: str
    blockCount: str
    headerCount: str
    tipHashes: list[str]
    difficulty: Number
    pastMedianTime: str
    virtualParentHashes: list[str]
    pruningPointHash: str
    virtualDaaScore: str
    sink: str


class BlueScoreResponse(BaseModel):
    blueScore: Number | None = None


class CoinSupplyResponse(BaseModel):
    circulatingSupply: str | None = None
    maxSupply: str | None = None


class DbCheckStatus(BaseModel):
    isSynced: bool | None = None
    blueScore: Number | None = None
    blueScoreDiff: Number | None = None
    acceptedTxBlockTime: Number | None = None
    acceptedTxBlockTimeDiff: Number | None = None


class DistributionTier(BaseModel):
    tier: Number
    count: Number
    amount: Number


class DistributionTiers(BaseModel):
    timestamp: Number
    tiers: list[DistributionTier]


class ExtraModel(BaseModel):
    color: str | None = None
    minerAddress: str | None = None
    minerInfo: str | None = None


class FeeEstimateBucket(BaseModel):
    feerate: Number | None = None
    estimatedSeconds: Number | None = None


class FeeEstimateResponse(BaseModel):
    priorityBucket: FeeEstimateBucket
    normalBuckets: list[FeeEstimateBucket]
    lowBuckets: list[FeeEstimateBucket]


class HttpValidationError(BaseModel):
    detail: list[ValidationError] | None = None


class HalvingResponse(BaseModel):
    nextHalvingTimestamp: Number | None = None
    nextHalvingDate: str | None = None
    nextHalvingAmount: Number | None = None


class HashrateHistoryResponse(BaseModel):
    daaScore: Number
    blueScore: Number
    timestamp: Number
    date_time: str
    difficulty: Number
    hashrate_kh: Number
    bits: Number | None = None


class HashrateResponse(BaseModel):
    hashrate: Number | None = None


class HealthResponse(BaseModel):
    kaspadServers: list[KaspadResponse]
    database: DbCheckStatus


class KaspadInfoResponse(BaseModel):
    mempoolSize: str | None = None
    serverVersion: str | None = None
    isUtxoIndexed: bool | None = None
    isSynced: bool | None = None
    p2pIdHashed: str | None = None


class KaspadResponse(BaseModel):
    kaspadHost: str | None = None
    serverVersion: str | None = None
    isUtxoIndexed: bool | None = None
    isSynced: bool | None = None
    p2pId: str | None = None
    blueScore: Number | None = None


class MarketCapResponse(BaseModel):
    marketcap: Number | None = None


class MaxHashrateResponse(BaseModel):
    blockheader: EndpointsGetHashrateBlockHeader
    hashrate: Number | None = None


class OutpointModel(BaseModel):
    transactionId: str | None = None
    index: Number | None = None


class ParentHashModel(BaseModel):
    parentHashes: list[str] | None = None


class PriceResponse(BaseModel):
    price: Number | None = None


class ScriptPublicKeyModel(BaseModel):
    scriptPublicKey: str | None = None


class SubmitTransactionRequest(BaseModel):
    transaction: SubmitTxModel
    allowOrphan: bool | None = None


class SubmitTransactionResponse(BaseModel):
    transactionId: str | None = None
    error: str | None = None


class SubmitTxInput(BaseModel):
    previousOutpoint: SubmitTxOutpoint
    signatureScript: str
    sequence: Number
    sigOpCount: Number


class SubmitTxModel(BaseModel):
    version: Number
    inputs: list[SubmitTxInput]
    outputs: list[SubmitTxOutput]
    lockTime: Number | None = None
    subnetworkId: str | None = None


class SubmitTxOutpoint(BaseModel):
    transactionId: str
    index: Number


class SubmitTxOutput(BaseModel):
    amount: Number
    scriptPublicKey: SubmitTxScriptPublicKey


class SubmitTxScriptPublicKey(BaseModel):
    version: Number
    scriptPublicKey: str


class TopAddress(BaseModel):
    rank: Number
    address: str
    amount: Number


class TopAddresses(BaseModel):
    timestamp: Number
    ranking: list[TopAddress]


class TransactionCount(BaseModel):
    total: Number


class TransactionCountResponse(BaseModel):
    timestamp: Number
    dateTime: str
    coinbase: Number
    regular: Number


class TxAcceptanceRequest(BaseModel):
    transactionIds: list[str]


class TxAcceptanceResponse(BaseModel):
    accepted: bool
    transactionId: str | None = None
    acceptingBlockHash: str | None = None
    acceptingBlueScore: Number | None = None
    acceptingTimestamp: Number | None = None


class TxInput(BaseModel):
    transaction_id: str
    index: Number
    previous_outpoint_hash: str
    previous_outpoint_index: str
    previous_outpoint_resolved: TxOutput | None = None
    previous_outpoint_address: str | None = None
    previous_outpoint_amount: Number | None = None
    signature_script: str | None = None
    sig_op_count: str | None = None


class TxMass(BaseModel):
    mass: Number
    storage_mass: Number
    compute_mass: Number


class TxModel(BaseModel):
    subnetwork_id: str | None = None
    transaction_id: str | None = None
    hash: str | None = None
    mass: str | None = None
    payload: str | None = None
    block_hash: list[str] | None = None
    block_time: Number | None = None
    version: Number | None = None
    is_accepted: bool | None = None
    accepting_block_hash: str | None = None
    accepting_block_blue_score: Number | None = None
    accepting_block_time: Number | None = None
    inputs: list[TxInput] | None = None
    outputs: list[TxOutput] | None = None


class TxOutput(BaseModel):
    transaction_id: str
    index: Number
    amount: Number
    script_public_key: str | None = None
    script_public_key_address: str | None = None
    script_public_key_type: str | None = None
    accepting_block_hash: str | None = None


class TxSearch(BaseModel):
    transactionIds: list[str] | None = None
    acceptingBlueScores: TxSearchAcceptingBlueScores | None = None


class TxSearchAcceptingBlueScores(BaseModel):
    gte: Number
    lt: Number


class UtxoCountResponse(BaseModel):
    count: Number


class UtxoModel(BaseModel):
    scriptPublicKey: ScriptPublicKeyModel
    amount: str | None = None
    blockDaaScore: str | None = None
    isCoinbase: bool | None = None


class UtxoRequest(BaseModel):
    addresses: list[str] | None = None


class UtxoResponse(BaseModel):
    outpoint: OutpointModel
    utxoEntry: UtxoModel
    address: str | None = None


class ValidationError(BaseModel):
    loc: list[str | Number]
    msg: str
    type: str


class VcBlockModel(BaseModel):
    hash: str
    blue_score: Number
    daa_score: Number | None = None
    timestamp: Number | None = None
    transactions: list[VcTxModel] | None = None


class VcTxInput(BaseModel):
    previous_outpoint_hash: str
    previous_outpoint_index: Number
    signature_script: str | None = None
    previous_outpoint_script: str | None = None
    previous_outpoint_address: str | None = None
    previous_outpoint_amount: Number | None = None


class VcTxModel(BaseModel):
    transaction_id: str
    is_accepted: bool | None = None
    inputs: list[VcTxInput] | None = None
    outputs: list[VcTxOutput] | None = None


class VcTxOutput(BaseModel):
    script_public_key: str
    script_public_key_address: str
    amount: Number


class VerboseDataModel(BaseModel):
    hash: str | None = None
    difficulty: Number | None = None
    selectedParentHash: str | None = None
    transactionIds: list[str] | None = None
    blueScore: str | None = None
    childrenHashes: list[str] | None = None
    mergeSetBluesHashes: list[str] | None = None
    mergeSetRedsHashes: list[str] | None = None
    isChainBlock: bool | None = None


class EndpointsGetBlocksBlockHeader(BaseModel):
    version: Number | None = None
    hashMerkleRoot: str | None = None
    acceptedIdMerkleRoot: str | None = None
    utxoCommitment: str | None = None
    timestamp: str | None = None
    bits: Number | None = None
    nonce: str | None = None
    daaScore: str | None = None
    blueWork: str | None = None
    parents: list[ParentHashModel] | None = None
    blueScore: str | None = None
    pruningPoint: str | None = None


class EndpointsGetHashrateBlockHeader(BaseModel):
    hash: str | None = None
    timestamp: str | None = None
    difficulty: Number | None = None
    daaScore: str | None = None
    blueScore: str | None = None
