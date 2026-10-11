"""R2 production JSON-bridge behavior assertions (standard library only)."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BRIDGE = Path(__file__).resolve().parents[1] / 'python' / 'graft_ops.py'


def bridge(op, **args):
    run = subprocess.run([sys.executable, '-I', '-B', str(BRIDGE)],
                         input=json.dumps({'op': op, 'args': args}), text=True,
                         capture_output=True, encoding='utf-8', timeout=90)
    return json.loads(run.stdout.splitlines()[-1])


def digest(seq):
    return 'sha256:' + hashlib.sha256(seq.upper().encode('ascii')).hexdigest()


def good(result):
    assert result['ok'] is True, result
    return result['result']


def bad(result):
    assert result['ok'] is False, result
    assert result.get('code') == 'INVALID_INPUT', result


def context(seq, *, contig='chr2', strand='+', start=10):
    return {'mode': 'genomic', 'assembly_accession': 'DECLARED_ASSEMBLY',
            'contig': contig, 'region_start_0': start,
            'region_end_0': start + len(seq),
            'input_strand_relative_to_reference': strand,
            'input_sequence_length': len(seq), 'input_sequence_hash': digest(seq)}


seq = 'TTTTACGTACGTACGTACGTACGTAGGCCCC'
with tempfile.TemporaryDirectory(prefix='graft-r2-') as tmp:
    fasta = Path(tmp) / 'ref.fa'
    fasta.write_text('>chr1 first\n' + 'A' * 100 + '\n>chr2 second\n'
                     + 'A' * 10 + seq + 'T' * 70 + '\n', encoding='utf-8')
    gc = context(seq)
    wrong = copy.deepcopy(gc)
    wrong.update(region_end_0=1023, region_start_0=1000,
                 input_sequence_length=23, input_sequence_hash='sha256:WRONG',
                 reference_verification={'status': 'verified'})
    bad(bridge('guide_enumerate', sequence=seq, genome_context=wrong))

    fake = copy.deepcopy(gc)
    fake['reference_verification'] = {'status': 'verified'}
    unverified = good(bridge('guide_enumerate', sequence=seq,
                             genome_context=fake))
    assert unverified['genome_context']['reference_verification']['status'] == 'unverified'
    assert all(c['genome_context']['reference_verification']['status'] == 'unverified'
               for c in unverified['candidates'])

    verified = good(bridge('guide_enumerate', sequence=seq,
                           genome_context=gc, reference_file=str(fasta)))
    assert verified['genome_context']['reference_verification']['status'] == 'verified'
    assert verified['method_version'] == 2 and \
           verified['genome_context']['reference_verification']['method_version'] == 2
    assert verified['genome_context']['reference_verification']['file_byte_hash'] != \
        verified['genome_context']['reference_verification']['record_seq_hash']
    assert all(c['genomic_start_0'] == 10 + c['start_0'] and
               c['genomic_cut_site_0'] == 10 + c['cut_site_0']
               for c in verified['candidates'])
    assert all(c['identity_schema']['genomic_locus']['record_seq_hash'] ==
               verified['genome_context']['reference_verification']['record_seq_hash']
               for c in verified['candidates'])

    # Header description / case / line breaks change file bytes, not locus identity.
    other = Path(tmp) / 'same-sequence.fa'
    other.write_text('>chr1 renamed\n' + 'A' * 100 + '\n>chr2 renamed\n'
                     + ('A' * 10 + seq + 'T' * 70).lower()[:50] + '\n'
                     + ('A' * 10 + seq + 'T' * 70).lower()[50:] + '\n',
                     encoding='utf-8')
    again = good(bridge('guide_enumerate', sequence=seq.lower(),
                        genome_context=gc, reference_file=str(other)))
    assert [c['guide_id'] for c in again['candidates']] == \
           [c['guide_id'] for c in verified['candidates']]
    assert again['genome_context']['reference_verification']['file_byte_hash'] != \
           verified['genome_context']['reference_verification']['file_byte_hash']

    missing = copy.deepcopy(gc)
    missing['contig'] = 'absent'
    bad(bridge('guide_enumerate', sequence=seq, genome_context=missing,
               reference_file=str(fasta)))
    duplicate = Path(tmp) / 'duplicate.fa'
    duplicate.write_text('>chr2 a\n' + seq + '\n>chr2 b\n' + seq + '\n', encoding='utf-8')
    bad(bridge('guide_enumerate', sequence=seq, genome_context=context(seq, start=0),
               reference_file=str(duplicate)))
    mismatch = Path(tmp) / 'mismatch.fa'
    mismatch.write_text('>chr2\n' + 'A' * 10 + 'C' * len(seq) + 'T' * 70 + '\n',
                        encoding='utf-8')
    bad(bridge('guide_enumerate', sequence=seq, genome_context=gc,
               reference_file=str(mismatch)))

    rc = seq.translate(str.maketrans('ACGT', 'TGCA'))[::-1]
    reverse = good(bridge('guide_enumerate', sequence=rc,
                          genome_context=context(rc, strand='-'),
                          reference_file=str(fasta)))
    assert all(c['genomic_start_0'] == 10 + len(seq) - c['end_0'] and
               c['genomic_cut_site_0'] == 10 + len(seq) - c['cut_site_0']
               for c in reverse['candidates'])

    candidate = verified['candidates'][0]
    annotated = copy.deepcopy(candidate)
    annotated['custom_annotation'] = {'nested': [1, {'source': 'original'}]}
    rescored = good(bridge('guide_score', candidates=[annotated], editor='SpCas9'))['candidates'][0]
    assert rescored.get('guide_id') == candidate['guide_id']
    assert rescored.get('custom_annotation') == annotated['custom_annotation']
    tampered = copy.deepcopy(candidate)
    tampered['start_0'] += 1
    bad(bridge('rank_candidates', candidates=[tampered], policy='pareto',
               objectives=['gc_abs_dev:min']))
    bad(bridge('evaluate_strategy', candidates=[candidate, tampered],
               strategy='deletion_pair'))
    conflict = copy.deepcopy(candidate)
    conflict['custom_note'] = 'different record'
    bad(bridge('rank_candidates', candidates=[candidate, conflict], policy='pareto',
               objectives=['gc_abs_dev:min']))

    old = [{'protospacer': 'ACGT', 'start_0': 0, 'end_0': 4,
            'strand': '+', 'gc_content': .5},
           {'protospacer': 'ACGT', 'start_0': 20, 'end_0': 24,
            'strand': '-', 'gc_content': .9}]
    rank = good(bridge('rank_candidates', candidates=old, policy='pareto',
                       objectives=['gc_abs_dev:min']))
    assert len(rank['pareto_front']) == 1 and rank['ranked'][0]['start_0'] == 0
    assert rank['method_version'] == 2
    assert len({c['record_key'] for c in rank['ranked']}) == 2
    assert all(c.get('guide_id') is None and c['identity_status'] == 'unresolved'
               for c in rank['ranked'])

    # A declared assembly change is a different source even with the same spacer.
    source_a = {'protospacer': 'ACGT', 'cut_site_0': 4,
                'genome_context': context(seq)}
    source_b = {'protospacer': 'ACGT', 'cut_site_0': 14,
                'genome_context': context(seq)}
    source_b['genome_context']['assembly_accession'] = 'OTHER_ASSEMBLY'
    cross = good(bridge('evaluate_strategy', candidates=[source_a, source_b],
                        strategy='deletion_pair'))
    assert cross['n_pairs_evaluated'] == 0 and cross['n_pairs_rejected_template_identity'] == 1

    # Full CDS in the original input frame. Upstream/downstream deletion keeps
    # the same coding sequence even when deletion length is not a multiple of 3.
    full = 'CCC' + 'ATGTCCGAATAA' + 'GGG'
    def translated(a, b, **extra):
        cands = [{'protospacer': 'A', 'cut_site_0': a, 'strand': '+'},
                 {'protospacer': 'B', 'cut_site_0': b, 'strand': '-'}]
        result = good(bridge('evaluate_strategy', candidates=cands,
                             sequence=full, cds_start_0=3, cds_end_0=15,
                             strategy='deletion_pair', **extra))
        return result['pairs'][0]
    upstream = translated(0, 3)['translation']
    assert upstream['translated_prefix'] == 'MSE*' and not upstream['premature_stop_detected']
    assert upstream['method_version'] == 2
    assert upstream['simulated_cds_interval_0based_half_open'] == [0, 12]
    one_base_upstream = translated(0, 1)['translation']
    assert one_base_upstream['translated_prefix'] == 'MSE*'
    assert one_base_upstream['cds_frame_preserved'] is True
    assert one_base_upstream['frame_preserved_by_length'] is False
    downstream = translated(15, 18)['translation']
    assert downstream['translated_prefix'] == 'MSE*' and not downstream['premature_stop_detected']
    inside = translated(7, 10)['translation']
    assert inside['translated_prefix'] == 'M**' and inside['premature_stop_detected']
    assert translated(2, 4)['translation']['translation_status'] == 'not_supported'
    assert translated(7, 10, genetic_code='mitochondrial')['translation']['translation_status'] == 'not_supported'

    mirrored = full.translate(str.maketrans('ACGT', 'TGCA'))[::-1]
    minus = good(bridge('evaluate_strategy', candidates=[
        {'protospacer': 'A', 'cut_site_0': 8, 'strand': '+'},
        {'protospacer': 'B', 'cut_site_0': 11, 'strand': '-'}],
        sequence=mirrored, cds_start_0=3, cds_end_0=15,
        cds_strand='-', strategy='deletion_pair'))['pairs'][0]['translation']
    assert minus['translated_prefix'] == inside['translated_prefix']
    assert minus['premature_stop_detected'] == inside['premature_stop_detected']

print('R2 Graft JSON bridge behavior PASS')
