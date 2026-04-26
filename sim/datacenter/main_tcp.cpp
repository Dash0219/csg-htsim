// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-
#include "config.h"
#include <sstream>

#include <iostream>
#include <string.h>
#include <math.h>
#include <unistd.h>
#include "network.h"
#include "randomqueue.h"
#include "shortflows.h"
#include "pipe.h"
#include "eventlist.h"
#include "logfile.h"
#include "loggers.h"
#include "clock.h"
#include "tcp.h"
#include "compositequeue.h"
#include "firstfit.h"
#include "topology.h"
#include "queue_lossless_input.h"
#include "connection_matrix.h"

#include "fat_tree_topology.h"
#include "fat_tree_switch.h"

#include <list>

#define PERIODIC 0
#include "main.h"

uint32_t RTT = 1; // per link delay in us
int DEFAULT_NODES = 432;
#define DEFAULT_QUEUE_SIZE 15

EventList eventlist;

void exit_error(char* progr) {
    cout << "Usage " << progr
         << " [-nodes N]\n\t[-conns C]\n\t[-cwnd cwnd_size]\n\t[-q queue_size]"
            "\n\t[-tm traffic_matrix_file]\n\t[-strat route_strategy (single,ecmp_host)]"
            "\n\t[-seed random_seed]\n\t[-end end_time_in_usec]"
            "\n\t[-mtu MTU]\n\t[-hop_latency x]\n\t[-switch_latency x]" << endl;
    exit(1);
}

int main(int argc, char **argv) {
    Clock c(timeFromSec(5 / 100.), eventlist);
    mem_b queuesize = DEFAULT_QUEUE_SIZE;
    linkspeed_bps linkspeed = speedFromMbps((double)HOST_NIC);
    int packet_size = 9000;
    uint32_t no_of_conns = 0, cwnd = 15, no_of_nodes = DEFAULT_NODES;
    uint32_t tiers = 3;
    double logtime = 0.25;
    stringstream filename(ios_base::out);
    simtime_picosec hop_latency = timeFromUs((uint32_t)1);
    simtime_picosec switch_latency = timeFromUs((uint32_t)0);
    queue_type qt = COMPOSITE;

    bool log_sink = false;
    bool log_tor_downqueue = false;
    bool log_tor_upqueue = false;
    bool log_traffic = false;
    bool log_switches = false;
    bool log_queue_usage = false;
    RouteStrategy route_strategy = NOT_SET;
    int seed = 13;
    int i = 1;

    filename << "logout.dat";
    int end_time = 1000; // microseconds

    queue_type snd_type = FAIR_PRIO;

    char* tm_file = NULL;
    char* topo_file = NULL;

    while (i < argc) {
        if (!strcmp(argv[i], "-o")) {
            filename.str(std::string());
            filename << argv[i+1];
            i++;
        } else if (!strcmp(argv[i], "-conns")) {
            no_of_conns = atoi(argv[i+1]);
            cout << "no_of_conns " << no_of_conns << endl;
            i++;
        } else if (!strcmp(argv[i], "-end")) {
            end_time = atoi(argv[i+1]);
            cout << "endtime(us) " << end_time << endl;
            i++;
        } else if (!strcmp(argv[i], "-nodes")) {
            no_of_nodes = atoi(argv[i+1]);
            cout << "no_of_nodes " << no_of_nodes << endl;
            i++;
        } else if (!strcmp(argv[i], "-tiers")) {
            tiers = atoi(argv[i+1]);
            cout << "tiers " << tiers << endl;
            assert(tiers == 2 || tiers == 3);
            i++;
        } else if (!strcmp(argv[i], "-queue_type")) {
            if (!strcmp(argv[i+1], "composite")) {
                qt = COMPOSITE;
            } else if (!strcmp(argv[i+1], "composite_ecn")) {
                qt = COMPOSITE_ECN;
            } else if (!strcmp(argv[i+1], "lossless")) {
                qt = LOSSLESS;
            } else if (!strcmp(argv[i+1], "lossless_input")) {
                qt = LOSSLESS_INPUT;
            } else {
                cout << "Unknown queue type " << argv[i+1] << endl;
                exit_error(argv[0]);
            }
            i++;
        } else if (!strcmp(argv[i], "-host_queue_type")) {
            if (!strcmp(argv[i+1], "prio")) {
                snd_type = PRIORITY;
            } else if (!strcmp(argv[i+1], "fair_prio")) {
                snd_type = FAIR_PRIO;
            } else {
                cout << "Unknown host queue type " << argv[i+1] << endl;
                exit_error(argv[0]);
            }
            i++;
        } else if (!strcmp(argv[i], "-log")) {
            if (!strcmp(argv[i+1], "sink")) {
                log_sink = true;
            } else if (!strcmp(argv[i+1], "tor_downqueue")) {
                log_tor_downqueue = true;
            } else if (!strcmp(argv[i+1], "tor_upqueue")) {
                log_tor_upqueue = true;
            } else if (!strcmp(argv[i+1], "switch")) {
                log_switches = true;
            } else if (!strcmp(argv[i+1], "traffic")) {
                log_traffic = true;
            } else if (!strcmp(argv[i+1], "queue_usage")) {
                log_queue_usage = true;
            } else {
                exit_error(argv[0]);
            }
            i++;
        } else if (!strcmp(argv[i], "-cwnd")) {
            cwnd = atoi(argv[i+1]);
            cout << "cwnd " << cwnd << endl;
            i++;
        } else if (!strcmp(argv[i], "-tm")) {
            tm_file = argv[i+1];
            cout << "traffic matrix input file: " << tm_file << endl;
            i++;
        } else if (!strcmp(argv[i], "-topo")) {
            topo_file = argv[i+1];
            i++;
        } else if (!strcmp(argv[i], "-q")) {
            queuesize = atoi(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i], "-logtime")) {
            logtime = atof(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i], "-linkspeed")) {
            linkspeed = speedFromMbps(atof(argv[i+1]));
            i++;
        } else if (!strcmp(argv[i], "-seed")) {
            seed = atoi(argv[i+1]);
            cout << "random seed " << seed << endl;
            i++;
        } else if (!strcmp(argv[i], "-mtu")) {
            packet_size = atoi(argv[i+1]);
            i++;
        } else if (!strcmp(argv[i], "-hop_latency")) {
            hop_latency = timeFromUs(atof(argv[i+1]));
            i++;
        } else if (!strcmp(argv[i], "-switch_latency")) {
            switch_latency = timeFromUs(atof(argv[i+1]));
            i++;
        } else if (!strcmp(argv[i], "-strat")) {
            if (!strcmp(argv[i+1], "single")) {
                route_strategy = SINGLE_PATH;
            } else if (!strcmp(argv[i+1], "ecmp_host")) {
                route_strategy = ECMP_FIB;
                FatTreeSwitch::set_strategy(FatTreeSwitch::ECMP);
            } else {
                cout << "Unknown strategy " << argv[i+1]
                     << " for TCP. Valid values: single, ecmp_host" << endl;
                exit_error(argv[0]);
            }
            i++;
        } else {
            cout << "Unknown parameter " << argv[i] << endl;
            exit_error(argv[0]);
        }
        i++;
    }

    srand(seed);
    srandom(seed);
    cout << "Parsed args" << endl;
    Packet::set_packet_size(packet_size);

    eventlist.setEndtime(timeFromUs((uint32_t)end_time));
    queuesize = memFromPkt(queuesize);

    if (route_strategy == NOT_SET) {
        fprintf(stderr, "Route Strategy not set. Use -strat ecmp_host or -strat single\n");
        exit(1);
    }

    cout << "Logging to " << filename.str() << endl;
    Logfile logfile(filename.str(), eventlist);
    cout << "Linkspeed set to " << linkspeed/1000000000 << "Gbps" << endl;
    logfile.setStartTime(timeFromSec(0));

    TcpSinkLoggerSampling sinkLogger(timeFromMs(logtime), eventlist);
    if (log_sink) {
        logfile.addLogger(sinkLogger);
    }
    TcpTrafficLogger traffic_logger;
    if (log_traffic) {
        logfile.addLogger(traffic_logger);
    }

    TcpSrc* tcpSrc;
    TcpSink* tcpSnk;

    Route* routeout, *routein;

    TcpRtxTimerScanner tcpRtxScanner(timeFromMs(10), eventlist);

    QueueLoggerFactory* qlf = NULL;
    if (log_tor_downqueue || log_tor_upqueue) {
        qlf = new QueueLoggerFactory(&logfile, QueueLoggerFactory::LOGGER_SAMPLING, eventlist);
        qlf->set_sample_period(timeFromUs(10.0));
    } else if (log_queue_usage) {
        qlf = new QueueLoggerFactory(&logfile, QueueLoggerFactory::LOGGER_EMPTY, eventlist);
        qlf->set_sample_period(timeFromUs(10.0));
    }

    FatTreeTopology* top;
    if (topo_file) {
        top = FatTreeTopology::load(topo_file, qlf, eventlist, queuesize, qt, snd_type);
    } else {
        FatTreeTopology::set_tiers(tiers);
        top = new FatTreeTopology(no_of_nodes, linkspeed, queuesize, qlf,
                                  &eventlist, NULL, qt, hop_latency,
                                  switch_latency, snd_type);
    }

    if (log_switches) {
        top->add_switch_loggers(logfile, timeFromUs(20.0));
    }

    no_of_nodes = top->no_of_nodes();
    cout << "actual nodes " << no_of_nodes << endl;

    vector<const Route*>*** net_paths;
    net_paths = new vector<const Route*>**[no_of_nodes];

    int** path_refcounts;
    path_refcounts = new int*[no_of_nodes];

    int* is_dest = new int[no_of_nodes];

    for (size_t s = 0; s < no_of_nodes; s++) {
        is_dest[s] = 0;
        net_paths[s] = new vector<const Route*>*[no_of_nodes];
        path_refcounts[s] = new int[no_of_nodes];
        for (size_t d = 0; d < no_of_nodes; d++) {
            net_paths[s][d] = NULL;
            path_refcounts[s][d] = 0;
        }
    }

    ConnectionMatrix* conns = new ConnectionMatrix(no_of_nodes);

    if (tm_file) {
        cout << "Loading connection matrix from " << tm_file << endl;
        if (!conns->load(tm_file)) {
            cout << "Failed to load connection matrix " << tm_file << endl;
            exit(-1);
        }
    } else if (no_of_conns > 0) {
        cout << "Running permutation with " << no_of_conns << " connections" << endl;
        conns->setPermutation(no_of_conns);
    } else {
        cout << "Loading connection matrix from standard input" << endl;
        conns->load(cin);
    }

    if (conns->N != no_of_nodes) {
        cout << "Connection matrix number of nodes is " << conns->N
             << " while I am using " << no_of_nodes << endl;
        exit(-1);
    }

    for (size_t c = 0; c < conns->failures.size(); c++) {
        failure* crt = conns->failures.at(c);
        cout << "Adding link failure switch type " << crt->switch_type
             << " Switch ID " << crt->switch_id
             << " link ID " << crt->link_id << endl;
        top->add_failed_link(crt->switch_type, crt->switch_id, crt->link_id);
    }

    vector<connection*>* all_conns = conns->getAllConnections();

    // Pre-populate paths for SINGLE_PATH strategy
    for (size_t c = 0; c < all_conns->size(); c++) {
        connection* crt = all_conns->at(c);
        int src = crt->src;
        int dest = crt->dst;
        path_refcounts[src][dest]++;
        path_refcounts[dest][src]++;

        if (route_strategy == SINGLE_PATH) {
            if (!net_paths[src][dest])
                net_paths[src][dest] = top->get_paths(src, dest);
            if (!net_paths[dest][src])
                net_paths[dest][src] = top->get_paths(dest, src);
        }
    }

    for (size_t c = 0; c < all_conns->size(); c++) {
        connection* crt = all_conns->at(c);
        int src = crt->src;
        int dest = crt->dst;

        tcpSrc = new TcpSrc(NULL, NULL, eventlist);
        tcpSrc->set_cwnd(cwnd * Packet::data_packet_size());
        tcpSnk = new TcpSink();

        tcpSrc->setName("tcp_" + ntoa(src) + "_" + ntoa(dest));
        logfile.writeName(*tcpSrc);

        tcpSnk->setName("tcp_sink_" + ntoa(src) + "_" + ntoa(dest));
        logfile.writeName(*tcpSnk);

        if (crt->size > 0)
            tcpSrc->set_flowsize(crt->size);

        tcpRtxScanner.registerTcp(*tcpSrc);

        switch (route_strategy) {
        case ECMP_FIB:
            {
                tcpSrc->set_dst(dest);
                tcpSnk->set_dst(src);

                Route* srctotor = new Route();
                srctotor->push_back(top->queues_ns_nlp[src][top->HOST_POD_SWITCH(src)][0]);
                srctotor->push_back(top->pipes_ns_nlp[src][top->HOST_POD_SWITCH(src)][0]);
                srctotor->push_back(top->queues_ns_nlp[src][top->HOST_POD_SWITCH(src)][0]->getRemoteEndpoint());

                Route* dsttotor = new Route();
                dsttotor->push_back(top->queues_ns_nlp[dest][top->HOST_POD_SWITCH(dest)][0]);
                dsttotor->push_back(top->pipes_ns_nlp[dest][top->HOST_POD_SWITCH(dest)][0]);
                dsttotor->push_back(top->queues_ns_nlp[dest][top->HOST_POD_SWITCH(dest)][0]->getRemoteEndpoint());

                tcpSrc->connect(*srctotor, *dsttotor, *tcpSnk, crt->start);

                assert(top->switches_lp[top->HOST_POD_SWITCH(src)]);
                assert(top->switches_lp[top->HOST_POD_SWITCH(dest)]);
                top->switches_lp[top->HOST_POD_SWITCH(src)]->addHostPort(src, tcpSrc->getFlowId(), tcpSrc);
                top->switches_lp[top->HOST_POD_SWITCH(dest)]->addHostPort(dest, tcpSrc->getFlowId(), tcpSnk);
                break;
            }
        case SINGLE_PATH:
            {
                int choice = rand() % net_paths[src][dest]->size();
                routeout = new Route(*(net_paths[src][dest]->at(choice)));
                routeout->push_back(tcpSnk);

                routein = new Route();
                routein->push_back(tcpSrc);

                tcpSrc->connect(*routeout, *routein, *tcpSnk, crt->start);
                break;
            }
        default:
            abort();
        }

        path_refcounts[src][dest]--;
        path_refcounts[dest][src]--;

        if (path_refcounts[src][dest] == 0 && net_paths[src][dest]) {
            delete net_paths[src][dest];
            net_paths[src][dest] = NULL;
        }
        if (path_refcounts[dest][src] == 0 && net_paths[dest][src]) {
            delete net_paths[dest][src];
            net_paths[dest][src] = NULL;
        }

        if (log_sink) {
            sinkLogger.monitorSink(tcpSnk);
        }
    }

    // Record setup metadata
    int pktsize = Packet::data_packet_size();
    logfile.write("# pktsize=" + ntoa(pktsize) + " bytes");
    logfile.write("# hostnicrate = " + ntoa(linkspeed/1000000) + " Mbps");
    double rtt = timeAsSec(timeFromUs(RTT));
    logfile.write("# rtt =" + ntoa(rtt));

    // GO!
    while (eventlist.doNextEvent()) {
    }
}
