import argparse, logging
from common.core import *
from validate_audio import validate
from convert_audio import convert
from quality_check import check
from generate_metadata import generate
from dataset_stats import generate as stats
from check_targets import check as targets

def run(config=None,force=False):
    logging.info("Validating raw recordings")
    validation=validate(config)
    logging.info("Converting supported raw recordings")
    conversion=convert(config,force)
    quality=check(config)
    utterances=generate(config)
    stats(config); target_rows=targets(config)
    summary={"files_discovered":len(validation),"valid":sum(r["status"]=="VALID" for r in validation),"warnings":sum(r["status"]=="WARNING" for r in validation),"invalid":sum(r["status"]=="INVALID" for r in validation),**conversion,"quality_failures":sum(r["status"]=="FAIL" for r in quality),"utterances":utterances}
    print("\nPipeline summary")
    for key,value in summary.items(): print(f"{key.replace('_',' ').title()}: {value}")
    print("Targets: "+", ".join(f"{r['language']} {r['current']}/{r['target']} {r['status']}" for r in target_rows))
    return summary

if __name__=="__main__":
    p=argparse.ArgumentParser(); p.add_argument("--config"); p.add_argument("--force",action="store_true"); a=p.parse_args(); setup_logging()
    try: run(a.config,a.force)
    except RuntimeError as e: logging.error("%s",e); raise SystemExit(2)
