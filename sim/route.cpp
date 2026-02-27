// -*- c-basic-offset: 4; indent-tabs-mode: nil -*-  
#include <climits>
#include "route.h"
#include "network.h"
#include "queue.h"
#include "pipe.h"

#define MAXQUEUES 10

Route::Route() : _hop_count(0), _reverse(NULL) {};

Route::Route(int size) : _hop_count(0), _reverse(NULL) {
    _sinklist.reserve(size);
    // _int_trace.reserve(size * sizeof(RouteINT_hop));
};

Route::Route(const Route& orig, PacketSink& dst) : _sinklist(orig.size()+1) {
    _path_id = orig.path_id();
    _reverse = orig._reverse;
    _hop_count = orig.hop_count();
    _no_of_paths = orig.no_of_paths();
    for (size_t i = 0; i < orig.size(); i++) {
        _sinklist[i] = orig.at(i);
    }
    _sinklist[orig.size()] = &dst;
    _hop_count++;

    // _int_trace = orig._int_trace;
}


Route*
Route::clone() const {
    Route *copy = new Route(_hop_count);
    copy->set_path_id(_path_id, _no_of_paths);
    copy->_reverse = _reverse;

    copy->_sinklist.resize(_sinklist.size());
    for (uint32_t i = 0; i < _sinklist.size(); i++) {
        copy->_sinklist[i] = _sinklist[i];
    }

    // copy->_int_trace = _int_trace;

    return copy;
}


void check_non_null(Route* rt){
    int fail = 0;
    for (size_t i=1;i<rt->size()-1;i++)
        if (rt->at(i)==NULL){
            fail = 1;
            break;
        }
  
    if (fail){
        //    cout <<"Null queue in route"<<endl;
        for (size_t i=1;i<rt->size()-1;i++)
            printf("%p ",rt->at(i));

        cout<<endl;
        assert(0);
    }
}

void
Route::add_endpoints(PacketSink *src, PacketSink* dst) {
    if (_reverse) {
        _reverse->push_back(src);
    }
}

void
Route::update_hopcount(PacketSink* sink) {
    if (dynamic_cast<Pipe*>(sink) != NULL) {
        _hop_count++;
    }
}

// void Route::add_int_hop(uint32_t hop,
//                         simtime_picosec ts,
//                         uint32_t qlen) const {
//     _int_trace.push_back({hop, ts, qlen});
// }

// const std::vector<RouteINT_hop>& Route::get_int_trace() const {
//     return _int_trace;
// }

// void Route::clear_int_trace() const {
//     _int_trace.clear();
// }
