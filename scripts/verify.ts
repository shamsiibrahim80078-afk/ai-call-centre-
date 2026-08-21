import * as fs from "fs";
import * as path from "path";
import hre from "hardhat";

type DeploymentFile = {
  network: string;
  contracts: Array<{
    contract_name: string;
    contract_address: string;
    token_name: string;
  }>;
};

/**
 * Verify previously deployed contracts on explorers.
 * Reads deployments/<network>-latest.json and uses Hardhat verify.
 *
 * Env: ETHERSCAN_API_KEY / BASESCAN_API_KEY
 */
async function main() {
  const networkName = hre.network.name;
  const label =
    networkName === "ethereum" || networkName === "mainnet"
      ? "ethereum"
      : networkName === "hardhat"
        ? "hardhat"
        : networkName;

  const filePath = path.join(
    __dirname,
    "..",
    "deployments",
    `${label === "hardhat" ? "hardhat" : label}-latest.json`
  );

  // Also try capitalized filename variants written by deploy.ts
  const candidates = [
    filePath,
    path.join(__dirname, "..", "deployments", `${hre.network.name}-latest.json`),
    path.join(__dirname, "..", "deployments", "Hardhat-latest.json"),
    path.join(__dirname, "..", "deployments", "Sepolia-latest.json"),
    path.join(__dirname, "..", "deployments", "Base-latest.json"),
    path.join(__dirname, "..", "deployments", "Ethereum-latest.json"),
  ];

  const existing = candidates.find((p) => fs.existsSync(p));
  if (!existing) {
    throw new Error(
      `No deployment file found for network '${hre.network.name}'. Run deploy_all.ts first.`
    );
  }

  const payload = JSON.parse(fs.readFileSync(existing, "utf8")) as DeploymentFile;
  console.log(`Verifying ${payload.contracts.length} contracts from ${existing}`);

  if (hre.network.name === "hardhat" || hre.network.name === "localhost") {
    console.log("Skipping explorer verification on local hardhat network (dry-run OK).");
    for (const item of payload.contracts) {
      console.log(`[DRY-RUN VERIFY] ${item.contract_name} @ ${item.contract_address}`);
    }
    return;
  }

  const [deployer] = await hre.ethers.getSigners();
  const constructorArgs: Record<string, unknown[]> = {
    WorkforceToken: ["Workforce Token", "WORK", hre.ethers.parseEther("1000000"), deployer.address],
    WorkforceTreasury: [deployer.address],
    SubscriptionManager: [deployer.address],
    AgentMarketplace: [deployer.address],
  };

  for (const item of payload.contracts) {
    const args = constructorArgs[item.contract_name] || [];
    try {
      await hre.run("verify:verify", {
        address: item.contract_address,
        constructorArguments: args,
      });
      console.log(`Verified ${item.contract_name} @ ${item.contract_address}`);
    } catch (error: any) {
      const message = String(error?.message || error);
      if (message.toLowerCase().includes("already verified")) {
        console.log(`Already verified ${item.contract_name}`);
      } else {
        throw error;
      }
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
