

def build_spatial_epi_qap_workflow(resource_pool, config, subject_id, \
                                   run_name, scan_id):
    
    # build pipeline for each subject, individually

    # ~ 5 min 20 sec per subject
    # (roughly 320 seconds)

    import os
    import sys

    import nipype.interfaces.io as nio
    import nipype.pipeline.engine as pe

    import nipype.interfaces.utility as util
    import nipype.interfaces.fsl.maths as fsl
    
    import glob
    import yaml

    from time import strftime
    from nipype import config
    from nipype import logging


    logger = logging.getLogger('workflow')

    output_dir = os.path.join(config["output_directory"], run_name, \
                              subject_id)

    try:
        os.makedirs(output_dir)
    except:
        if not os.path.isdir(output_dir):
            err = "[!] Output directory unable to be created.\n" \
                  "Path: %s\n\n" % output_dir
            raise Exception(err)
        else:
            pass
    log_dir = output_dir

    config.update_config({'logging': {'log_directory': log_dir, 'log_to_file': True}})
    logging.update_logging(config)

    # take date+time stamp for run identification purposes
    unique_pipeline_id = strftime("%Y%m%d%H%M%S")
    pipeline_start_stamp = strftime("%Y-%m-%d_%H:%M:%S")

    logger.info("Pipeline start time: %s" % pipeline_start_stamp)



    # get the directory this script is in (not the current working one)

    # doing this so that we can properly call the QAP functions from
    # "spatial_qc.py" in qclib; they are called from within Nipype util
    # Function nodes, and cannot properly import files from the directory they
    # are stored in
    script_dir = os.path.dirname(os.path.realpath('__file__'))

    qclib_dir = os.path.join(script_dir, "qclib")

    sys.path.insert(0, qclib_dir)

        
    # for QAP spreadsheet generation only
    config["subject_id"] = subject_id
    config["scan_id"] = scan_id
    


    workflow = pe.Workflow(name=subject_id)

    current_dir = os.getcwd()
    workflow.base_dir = os.path.join(config["working_directory"], scan_id)
    
    
    # update that resource pool with what's already in the output directory
    for resource in os.listdir(output_dir):
    
        if os.path.isdir(os.path.join(output_dir,resource)) and resource not in resource_pool.keys():
        
            resource_pool[resource] = glob.glob(os.path.join(output_dir, \
                                          resource, "*"))[0]
                 

    # resource pool check
    invalid_paths = []
    
    for resource in resource_pool.keys():
    
        if not os.path.isfile(resource_pool[resource]):
        
            invalid_paths.append((resource, resource_pool[resource]))
            
            
    if len(invalid_paths) > 0:
        
        err = "\n\n[!] The paths provided in the subject list to the " \
              "following resources are not valid:\n"
        
        for path_tuple in invalid_paths:
        
            err = err + path_tuple[0] + ": " + path_tuple[1] + "\n"
                  
        err = err + "\n\n"
        
        raise Exception(err)
                  
    
    
    # start connecting the pipeline
       
    if "qap_spatial_epi" not in resource_pool.keys():

        from qclib.qap_workflows import qap_spatial_epi_workflow

        workflow, resource_pool = \
            qap_spatial_epi_workflow(workflow, resource_pool, config)

    

    # set up the datasinks
    new_outputs = 0
    
    for output in resource_pool.keys():
    
        # we use a check for len()==2 here to select those items in the
        # resource pool which are tuples of (node, node_output), instead of
        # the items which are straight paths to files

        # resource pool items which are in the tuple format are the outputs
        # that have been created in this workflow because they were not
        # present in the subject list YML (the starting resource pool) and had
        # to be generated

        if len(resource_pool[output]) == 2:
    
            ds = pe.Node(nio.DataSink(), name='datasink_%s' % output)
            ds.inputs.base_directory = output_dir
    
            node, out_file = resource_pool[output]

            workflow.connect(node, out_file, ds, output)
            
            new_outputs += 1
         
            
       
    # run the pipeline (if there is anything to do)
    if new_outputs > 0:
        
        workflow.run(plugin='MultiProc', plugin_args= \
                         {'n_procs': config["num_cores_per_subject"]})

    else:

        print "\nEverything is already done for subject %s." % subject_id


    pipeline_end_stamp = strftime("%Y-%m-%d_%H:%M:%S")

    logger.info("Pipeline end time: %s" % pipeline_end_stamp)



    return workflow



def run(subject_list, pipeline_config_yaml, scan_id, cloudify=False):

    import os
    import yaml
    from multiprocessing import Process
    
    
    if not cloudify:
        with open(subject_list, "r") as f:
            subject_list = yaml.load(f)
        
    with open(pipeline_config_yaml,"r") as f:
        config = yaml.load(f)
        

    try:
        os.makedirs(config["output_directory"])
    except:
        if not os.path.isdir(config["output_directory"]):
            err = "[!] Output directory unable to be created.\n" \
                  "Path: %s\n\n" % config["output_directory"]
            raise Exception(err)
        else:
            pass


    try:
        os.makedirs(config["working_directory"])
    except:
        if not os.path.isdir(config["working_directory"]):
            err = "[!] Output directory unable to be created.\n" \
                  "Path: %s\n\n" % config["working_directory"]
            raise Exception(err)
        else:
            pass


    
    # get the pipeline config file name, use it as the run name
    run_name = pipeline_config_yaml.split("/")[-1].split(".")[0]

    if not cloudify:
        
        procss = [Process(target=build_spatial_epi_qap_workflow, \
                     args=(subject_list[sub], config, sub, run_name, \
                     scan_id)) for sub in subject_list.keys()]
                          
                          
        pid = open(os.path.join(config["output_directory"], 'pid.txt'), 'w')
    
        # Init job queue
        job_queue = []

        # If we're allocating more processes than are subjects, run them all
        if len(subject_list) <= config["num_subjects_at_once"]:
    
            """
            Stream all the subjects as sublist is
            less than or equal to the number of 
            subjects that need to run
            """
    
            for p in procss:
                p.start()
                print >>pid,p.pid
    
        # Otherwise manage resources to run processes incrementally
        else:
    
            """
            Stream the subject workflows for preprocessing.
            At Any time in the pipeline c.numSubjectsAtOnce
            will run, unless the number remaining is less than
            the value of the parameter stated above
            """
    
            idx = 0
    
            while(idx < len(subject_list)):
    
                # If the job queue is empty and we haven't started indexing
                if len(job_queue) == 0 and idx == 0:
    
                    # Init subject process index
                    idc = idx
    
                    # Launch processes (one for each subject)
                    for p in procss[idc: idc+config["num_subjects_at_once"]]:
    
                        p.start()
                        print >>pid,p.pid
                        job_queue.append(p)
                        idx += 1
    
                # Otherwise, jobs are running - check them
                else:
    
                    # Check every job in the queue's status
                    for job in job_queue:
    
                        # If the job is not alive
                        if not job.is_alive():
    
                            # Find job and delete it from queue
                            print 'found dead job ', job
                            loc = job_queue.index(job)
                            del job_queue[loc]
    
                            # ..and start the next available process (subject)
                            procss[idx].start()
    
                            # Append this to job queue and increment index
                            job_queue.append(procss[idx])
                            idx += 1

                    # Add sleep so while loop isn't consuming 100% of CPU
                    time.sleep(2)
    
        pid.close()


    else:

        # run on cloud
        sub = subject_list.keys()[0]
        build_spatial_epi_qap_workflow(subject_list[sub], config, sub, \
                                       run_name, scan_id)



def main():

    import argparse

    parser = argparse.ArgumentParser()

    group = parser.add_argument_group("Regular Use Inputs (non-cloud runs)")

    cloudgroup = parser.add_argument_group("AWS Cloud Inputs (only required "\
                                           "for AWS Cloud runs)")

    req = parser.add_argument_group("Required Inputs")


    cloudgroup.add_argument('--subj_idx', type=int, \
                                help='Subject index to run')

    cloudgroup.add_argument('--creds_path', type=str, \
                                help='Path to AWS creds')


    # Subject list (YAML file)
    group.add_argument("--sublist", type=str, \
                            help="filepath to subject list YAML")

    req.add_argument("config", type=str, \
                            help="filepath to pipeline configuration YAML")

    req.add_argument("scan_name", type=str, \
                            help="name of the scan to run for the QAP " \
                                 "measures")


    args = parser.parse_args()


    # checks
    if args.subj_idx and not args.creds_path and not args.sublist:
        print "\n[!] You provided --subj_idx, but not --creds_path. When " \
              "executing cloud-based runs, please provide both inputs.\n"

    elif args.creds_path and not args.subj_idx and not args.sublist:
        print "\n[!] You provided --creds_path, but not --subj_idx. When " \
              "executing cloud-based runs, please provide both inputs.\n"

    elif not args.sublist and not args.subj_idx and not args.creds_path:
        print "\n[!] Either --sublist is required for regular runs, or both "\
              "--subj_idx and --creds_path for cloud-based runs.\n"

    elif args.sublist and args.subj_idx and args.creds_path:
        print "\n[!] Either --sublist is required for regular runs, or both "\
              "--subj_idx and --creds_path for cloud-based runs, but not " \
              "all three. (I'm not sure which you are trying to do!)\n"

    elif args.sublist and (args.subj_idx or args.creds_path):
        print "\n[!] Either --sublist is required for regular runs, or both "\
              "--subj_idx and --creds_path for cloud-based runs. (I'm not " \
              "sure which you are trying to do!)\n"

    else:

        if args.subj_idx and args.creds_path:

            # ---- Cloud-ify! ----
            # Import packages
            from qclib.cloud_utils import dl_subj_from_s3, upl_qap_output

            # Download and build subject dictionary from S3
            sub_dict = dl_subj_from_s3(args.subj_idx, 'rest', args.creds_path)

            # Run it
            run(sub_dict, args.config, args.scan_name, cloudify=True)

            # Upload results
            upl_qap_output(args.config)


        elif args.sublist:

            # Run it
            run(args.sublist, args.config, args.scan_name, cloudify=False)



if __name__ == "__main__":
    main()



