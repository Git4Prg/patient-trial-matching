import datetime
import json
import logging
from typing import List

from tqdm import tqdm

from trec_cds.data.load_data_from_file import load_jsonl
from trec_cds.features.build_features import ClinicalTrialsFeatures
from trec_cds.features.index_clinical_trials import Indexer
from trec_cds.models.trec_evaluation import read_bm25, evaluate

feature_builder = ClinicalTrialsFeatures(spacy_language_model_name="en_core_sci_lg")


def get_sections(dict_item, options):
    sections = []
    positive_keywords = ["_".join(x.split()) for x in dict_item["positive_entities"]]
    negative_keywords = [
        f'no_{"_".join(x.split())}' for x in dict_item["negated_entities"]
    ]
    past_history_keywords = [
        f'PMH_{"_".join(x.split())}' for x in dict_item["pmh_entities"]
    ]
    family_keywords = [f'FH_{"_".join(x.split())}' for x in dict_item["fh_entities"]]
    if "positive" in options:
        sections.extend(positive_keywords)
    if "negative" in options:
        sections.extend(negative_keywords)
    if "pmh" in options:
        sections.extend(past_history_keywords)
    if "fh" in options:
        sections.extend(family_keywords)
    return sections


def build_query(patient, options):
    sections = get_sections(patient, options=options)
    text = feature_builder.preprocess_text(patient["description"], lemmatised=False)
    # text = feature_builder.preprocess_text(patient['current_medical_history'], lemmatised=True)
    text.extend(sections)
    return text


def swap_exclusion(exclusion_dict):
    exclusion_dict["positive_entities_1"] = exclusion_dict["negated_entities"]
    exclusion_dict["negated_entities"] = exclusion_dict["positive_entities"]
    exclusion_dict["positive_entities"] = exclusion_dict["positive_entities_1"]
    exclusion_dict.pop("positive_entities_1", None)

    return exclusion_dict


def build_index_input(clinical_trial, options):
    exclusion_dict = swap_exclusion(exclusion_dict=clinical_trial["exclusion_criteria"])
    exclusion_sections = get_sections(exclusion_dict, options=options)

    sections = get_sections(clinical_trial["inclusion_criteria"], options=options)
    input_text = f"{clinical_trial['brief_summary']} {clinical_trial['official_title']} {clinical_trial['brief_title']} {clinical_trial['detailed_description']} {' '.join(clinical_trial['conditions'])}  {' '.join(clinical_trial['inclusion'])}"
    # input_text = f"{clinical_trial['brief_summary']} {clinical_trial['official_title']} {clinical_trial['brief_title']} {clinical_trial['detailed_description']} {' '.join(clinical_trial['conditions'])}  {clinical_trial['criteria']}"
    text = feature_builder.preprocess_text(input_text, lemmatised=False)
    text.extend(sections)
    text.extend(exclusion_sections)
    return text


if __name__ == "__main__":
    # for options in [['positive', 'negative', 'pmh', 'fh'], ['positive', 'negative', 'pmh'], ['positive', 'negative', 'fh'], ['positive', 'negative'], ['positive'], ['positive'], ['negative']]:
    options = ["positive", "negative", "fh"]
    # options = []
    print(options)
    print("lemmatised")
    run_name = "keywords_experiment-anf-i"
    return_top_n = 500
    submission_folder = "/newstorage4/wkusa/data/trec_cds/data/processed/ecir2023/ie/"

    patient_file = "topics2021"
    infile = f"../data/processed/{patient_file}.jsonl"

    patients = load_jsonl(infile)
    print([patient["is_smoker"] for patient in patients])
    print([patient["is_drinker"] for patient in patients])

    trials_file = "/newstorage4/wkusa/data/trec_cds/trials_parsed-new.jsonl"
    trials = load_jsonl(trials_file)
    print(len(trials))

    clinical_trials_text: List[List[str]] = []
    for clinical_trial in tqdm(trials):
        text = build_index_input(clinical_trial=clinical_trial, options=options)
        text = [x.lower() for x in text if x.strip()]
        clinical_trials_text.append(text)

    lookup_table = {x_index: x["nct_id"] for x_index, x in enumerate(trials)}

    indexer = Indexer()
    indexer.index_text(text=clinical_trials_text, lookup_table=lookup_table)

    output_scores = {}
    for patient in patients:
        doc = build_query(patient=patient, options=options)
        doc = [x.lower() for x in doc if x.strip()]

        output_scores[patient["patient_id"]] = indexer.query_single(
            query=doc, return_top_n=return_top_n
        )

    with open(f"{submission_folder}/bm25p-{run_name}-221020.json", "w") as fp:
        json.dump(output_scores, fp)

    results_file = f"{submission_folder}/bm25p-{run_name}-{datetime.datetime.today()}"
    logging.info("Converting total number of %d topics", len(output_scores))
    with open(results_file, "w") as fp:
        for topic_no in output_scores:
            logging.info("working on topic: %s", topic_no)

            sorted_results = {
                k: v
                for k, v in sorted(
                    output_scores[topic_no].items(),
                    key=lambda item: item[1],
                    reverse=True,
                )
            }

            logging.info("normalizing results")
            max_value = max(sorted_results.values())
            sorted_results = {k: v / max_value for k, v in sorted_results.items()}

            for rank, doc in enumerate(sorted_results):
                if rank >= 1000:  # TREC submission allows max top 1000 results
                    break
                score = sorted_results[doc]

                line = f"{topic_no} Q0 {doc} {rank + 1} {score} {run_name}\n"
                fp.write(line)

    print("NDCG:")
    output_results = evaluate(run=read_bm25(results_file),
                              qrels_path="/home/wkusa/projects/trec-cds/data/external/qrels2021.txt",
                              eval_measures={"ndcg_cut_10", "P_10", "recip_rank", "ndcg_cut_5"})
    print("\n\nprecison, RR:")
    output_results += evaluate(run=read_bm25(results_file),
                               qrels_path="/home/wkusa/projects/TREC/trec-cds/data/external/qrels2021_binary.txt",
                               eval_measures={"P_10", "recip_rank"})
    print("\n\n")

    with open(f"{submission_folder}/bm25p-{run_name}-221020-results", "w") as fp:
        fp.write(output_results)
