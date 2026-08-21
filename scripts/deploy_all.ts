import { deployWorkforceStack } from "./deploy";

/**
 * Deploy the full workforce contract stack to the selected Hardhat network.
 * Networks: hardhat (dry-run), sepolia, base, ethereum
 *
 * Env:
 * - DEPLOYER_PRIVATE_KEY / PRIVATE_KEY
 * - SEPOLIA_RPC_URL / BASE_RPC_URL / ETHEREUM_RPC_URL
 */
async function main() {
  const records = await deployWorkforceStack();
  console.log(`deploy_all complete: ${records.length} contracts`);
  for (const record of records) {
    console.log(
      `${record.contract_name} | ${record.network} | ${record.contract_address} | ${record.tx_hash}`
    );
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
